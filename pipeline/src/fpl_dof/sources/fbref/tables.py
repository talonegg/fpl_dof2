"""A very small HTML table reader, for statistics pages that publish semantic tables.

Deliberately not a general HTML parser. It looks for one table by id and reads cells by their
``data-stat`` attribute, which is a stable, machine-readable contract the page already offers —
far more durable than counting columns, which is what breaks the moment a column is inserted.

Two page quirks it handles, because both are load-bearing:

* Secondary tables are shipped inside HTML comments. The markup inside them is ordinary; only the
  comment wrapper hides it, so the wrapper is removed before parsing.
* A player's own identifier is on the row's header cell as ``data-append-csv``. Without it the only
  key would be the name, and names are exactly what entity resolution must not have to trust.
"""

from __future__ import annotations

from html.parser import HTMLParser

#: The attribute carrying the site's own stable player id.
PLAYER_ID_ATTR = "data-append-csv"


class _TableReader(HTMLParser):
    def __init__(self, table_id: str) -> None:
        super().__init__(convert_charrefs=True)
        self._table_id = table_id
        self._in_table = False
        self._depth = 0
        self._row: dict[str, str] | None = None
        self._cell: str | None = None
        self._text: list[str] = []
        self.rows: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: (value or "") for key, value in attrs}
        if tag == "table":
            if attributes.get("id") == self._table_id:
                self._in_table = True
                self._depth = 1
            elif self._in_table:
                self._depth += 1
            return
        if not self._in_table:
            return
        if tag == "tr":
            self._row = {}
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = attributes.get("data-stat") or ""
            self._text = []
            player_id = attributes.get(PLAYER_ID_ATTR)
            if player_id:
                self._row["player_id"] = player_id

    def handle_endtag(self, tag: str) -> None:
        if not self._in_table:
            return
        if tag == "table":
            self._depth -= 1
            if self._depth <= 0:
                self._in_table = False
            return
        if tag in {"td", "th"} and self._row is not None and self._cell:
            self._row[self._cell] = "".join(self._text).strip()
            self._cell = None
            self._text = []
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._text.append(data)


def uncomment(html: str) -> str:
    """Reveal tables that ship inside HTML comments, leaving everything else alone."""
    return html.replace("<!--", "").replace("-->", "")


def parse_table(html: str, table_id: str) -> list[dict[str, str]]:
    """Every data row of one table, as ``data-stat`` name to cell text.

    Header and separator rows come back without a player id and are dropped by the caller rather
    than here: which rows are meaningful is the caller's question, not the parser's.
    """
    reader = _TableReader(table_id)
    reader.feed(uncomment(html))
    reader.close()
    return reader.rows


__all__ = ["PLAYER_ID_ATTR", "parse_table", "uncomment"]
