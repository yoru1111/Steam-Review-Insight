"""Distinct global Steam chart snapshots. No ranks are inferred from candidate metadata."""
from datetime import datetime, timezone
from html.parser import HTMLParser
import re
import time

from .collector import CollectionError
from .game_details import GameDetails
from .public_steam import PublicSteamClient
from .schema import app_id, uint
from .storage import now, read_json, write_json, writer_lock

CHARTS = {
    "top_sellers": ("https://store.steampowered.com/charts/topselling/global", "revenue", 1800, "Steam Top Sellers"),
    "most_played": ("https://store.steampowered.com/charts/mostplayed", "current_concurrent_players", 600, "Steam Most Played"),
}


class ChartRows(HTMLParser):
    """Read semantic table rows without depending on generated CSS class names."""
    def __init__(self):
        super().__init__()
        self.rows, self.cells, self.text, self.identifier = [], None, None, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.cells, self.identifier = [], None
        elif tag == "td" and self.cells is not None:
            self.text = []
        elif tag == "a" and self.cells is not None:
            match = re.match(r"https://store\.steampowered\.com/app/([0-9]+)(?:/|\?|$)", attrs.get("href", ""))
            if match:
                self.identifier = int(match[1])

    def handle_data(self, value):
        if self.text is not None:
            self.text.append(value)

    def handle_endtag(self, tag):
        if tag == "td" and self.text is not None:
            self.cells.append(" ".join("".join(self.text).split()))
            self.text = None
        elif tag == "tr" and self.cells is not None:
            if self.identifier:
                self.rows.append((self.identifier, self.cells))
            self.cells, self.text = None, None


def parse_chart(text, ranking_type):
    parser = ChartRows()
    parser.feed(text)
    games = []
    for identifier, cells in parser.rows:
        if len(cells) != 5 or uint(cells[0]) is None or not cells[1]:
            raise CollectionError("Steam chart table format changed")
        game = {"rank": int(cells[0]), "app_id": identifier, "name": cells[1], "current_players": None,
                "peak_today_players": None}
        if ranking_type == "most_played":
            for index, field in ((3, "current_players"), (4, "peak_today_players")):
                value = cells[index].replace(",", "").replace(" ", "")
                if uint(value) is None:
                    raise CollectionError("Steam player count format changed")
                game[field] = int(value)
        games.append(game)
    if not games:
        raise CollectionError("Steam chart has no public table rows")
    validate_games(games, ranking_type)
    return games


def validate_games(games, ranking_type):
    if not isinstance(games, list) or not games or len(games) > 100:
        raise ValueError("Ranking games must contain 1 to 100 rows")
    ids, ranks = set(), set()
    for game in games:
        if (not isinstance(game, dict) or type(game.get("app_id")) is not int
                or app_id(game.get("app_id")) is None):
            raise ValueError("Invalid ranking App ID")
        rank = uint(game.get("rank"))
        if type(game.get("rank")) is not int or not rank or rank > 100 or rank in ranks or game["app_id"] in ids:
            raise ValueError("Ranking IDs and ranks must be unique")
        if not isinstance(game.get("name"), str) or not game["name"].strip():
            raise ValueError("Ranking game name is required")
        if ranking_type == "most_played" and uint(game.get("current_players")) is None:
            raise ValueError("Current players are required for most_played")
        ids.add(game["app_id"])
        ranks.add(rank)


class Rankings:
    def __init__(self, root, *, client=None, details=None, ttl_seconds=None, clock=time.time):
        self.root, self.directory = root, root / "data/rankings"
        self.client = client or PublicSteamClient()
        self.details = details or GameDetails(root, client=self.client)
        self.ttl_seconds = ttl_seconds or {}
        self.clock = clock

    def import_snapshot(self, payload):
        kind = payload.get("ranking_type")
        if kind not in CHARTS:
            raise ValueError("ranking_type must be top_sellers or most_played")
        url, metric, _, source = CHARTS[kind]
        if (payload.get("source_url") != url or payload.get("ranking_metric") != metric
                or payload.get("ranking_scope") != "global"):
            raise ValueError("Snapshot source, metric and global scope must match the official chart")
        try:
            observed = datetime.fromisoformat(payload["fetched_at_utc"].replace("Z", "+00:00"))
            if observed.tzinfo is None or observed > datetime.now(timezone.utc):
                raise ValueError
        except (KeyError, AttributeError, TypeError, ValueError):
            raise ValueError("Snapshot needs an actual, timezone-aware observation time") from None
        validate_games(payload.get("games"), kind)
        # Keep only public chart fields, never arbitrary snapshot fields or contact information.
        games = [{key: row.get(key) for key in ("rank", "app_id", "name", "current_players", "peak_today_players")}
                 for row in payload["games"]]
        result = {"ranking_type": kind, "ranking_metric": metric, "ranking_scope": "global",
                  "source": source, "source_url": url, "fetched_at_utc": observed.isoformat(),
                  "fetched_at": observed.timestamp(), "games": sorted(games, key=lambda row: row["rank"]),
                  "acquisition_method": "imported_official_chart_snapshot"}
        with writer_lock(self.directory):
            write_json(self.directory / f"{kind}.json", result)
        return result

    def get(self, ranking_type, limit=20, refresh=False, include_details=True):
        if ranking_type not in CHARTS or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Choose a supported ranking_type and limit between 1 and 100")
        url, metric, default_ttl, source = CHARTS[ranking_type]
        ttl = self.ttl_seconds.get(ranking_type, default_ttl)
        error = None
        with writer_lock(self.directory):
            cached = read_json(self.directory / f"{ranking_type}.json")
            stale = not cached or self.clock() - cached["fetched_at"] >= ttl
            cache_used = bool(cached)
            if refresh or stale:
                try:
                    games = parse_chart(self.client.get(url + "?l=english", as_json=False), ranking_type)
                    cached = {
                        "ranking_type": ranking_type, "ranking_metric": metric, "ranking_scope": "global",
                        "source": source, "source_url": url, "fetched_at": self.clock(), "fetched_at_utc": now(),
                        "games": games, "acquisition_method": "public_official_chart_html",
                    }
                    write_json(self.directory / f"{ranking_type}.json", cached)
                    cache_used, stale = False, False
                except (CollectionError, ValueError) as exc:
                    error = str(exc)
            if not cached:
                return {"ranking_type": ranking_type, "ranking_metric": metric, "ranking_scope": "global",
                        "source": source, "source_url": url, "fetched_at_utc": None, "cache_used": False,
                        "cache_stale": None, "status": "unavailable", "error": error, "games": []}
            result = {**cached, "games": cached["games"][:limit], "cache_used": cache_used,
                      "cache_stale": stale, "status": "stale" if stale else "available", "error": error}
        games = []
        for row in result["games"]:
            details = self.details.get(row["app_id"]) if include_details else {}
            games.append({
                **row, "header_image": details.get("header_image"), "genres": details.get("genres", []),
                "release_date": details.get("release_date"), "ranking_source": source,
                "ranking_fetched_at_utc": result["fetched_at_utc"],
                "details_fetched_at_utc": details.get("fetched_at_utc"),
                "metadata_status": details.get("metadata_status"), "game_type": details.get("game_type"),
            })
        return {**result, "games": games}
