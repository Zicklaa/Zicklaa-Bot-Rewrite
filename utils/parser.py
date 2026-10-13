"""Parser für die Zeitangabe von ``/remindme at`` (Grammatik: rm_grammar.peg)."""

from pathlib import Path

from parsimonious.grammar import Grammar
from parsimonious.nodes import NodeVisitor

GRAMMAR_FILE = Path(__file__).with_name("rm_grammar.peg")


def _number(key: str):
    """Erzeugt einen Visitor, der den Knotentext als ``{key: int}`` zurückgibt."""
    return lambda self, node, _children: {key: int(node.text)}


class RemindmeParser(NodeVisitor):
    """Wandelt Eingaben wie ``01.09.2025 15:30 Text`` in ein Dict um.

    Ergebnis z. B.: ``{"remind_time": {"day": 1, "month": 9, …}, "msg": "Text"}``
    """

    UNIT_TO_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}

    def __init__(self, grammar: str | None = None):
        self.grammar = Grammar(grammar or GRAMMAR_FILE.read_text(encoding="utf-8"))

    def append_children(self, _node, visited_children):
        """Führt die Dicts aller Kind-Knoten zu einem Dict zusammen."""
        output = {}
        for child in visited_children:
            if isinstance(child, list):
                child = child[0] if child else None
            if child is not None:
                output.update(child)
        return output

    # Zusammengesetzte Regeln reichen nur die Ergebnisse ihrer Kinder weiter
    visit_rm = visit_method = visit_HMS = visit_Date = visit_Time = append_children
    visit_DateTime = visit_DMY = visit_YMD = append_children

    # Einzelne Zahlenfelder
    visit_Year = visit_Year4 = _number("year")
    visit_Month = _number("month")
    visit_Day = _number("day")
    visit_Hour = _number("hour")
    visit_Minute = _number("minute")
    visit_Second = _number("second")

    def visit_msg(self, node, _children):
        return {"msg": node.text.strip()}

    def visit_all(self, _node, _children):
        return {"all": True}

    def visit_RemindTime(self, _node, visited_children):
        return {"remind_time": visited_children[-1]} if visited_children else {}

    def visit_DateSep(self, _node, _children):
        return None

    def visit_Duration(self, node, _children):
        # node.match enthält die Regex-Gruppen (Zahl, Einheit) aus rm_grammar.peg
        amount, unit = node.match.groups()
        return {"duration_seconds": int(amount) * self.UNIT_TO_SECONDS[unit]}

    def generic_visit(self, node, visited_children):
        return visited_children or node
