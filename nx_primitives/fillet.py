"""Fillet (из original solid.py)."""
from __future__ import annotations

import NXOpen

from .extrude_core import Extrude

class Fillet:
    """
    Скругление рёбер тела.

    Parameters
    ----------
    extrude : Extrude
        Объект, через который ищутся рёбра по имени (нужен только для
        элементов-СТРОК/кортежей в edges; для готовых NXOpen.Edge не
        используется).

        ВАЖНО: extrude.body должен быть АКТИВНЫМ (не suppressed) телом.
        Если тело участвовало как `tools` в Union/Subtract/Intersect -
        оно подавляется сразу после операции. find_edge() теперь САМ
        умеет переключаться на поиск по координатам на результирующем
        теле в этом случае (см. Extrude.find_edge) - но это подстраховка
        на крайний случай, а не рекомендуемый способ. Рекомендуется
        по-прежнему: сначала получить готовые NXOpen.Edge через
        extrude.edges_on(merged.body, names) / edges_after_boolean(...) /
        attachment_seam(...), а вторым аргументом передать ЛЮБОЙ ДРУГОЙ
        активный Extrude (например target, `plate`) - он используется
        только как "якорь" для готовых Edge, поиск по имени для них не
        выполняется.
    edges : list
        Список, где каждый элемент может быть:
        - строкой "ab"            -> ребро внешнего контура (индекс профиля 0)
        - кортежем ("ab", 1)      -> ребро профиля с индексом 1 (например,
          первое отверстие)
        - готовым NXOpen.Edge     -> используется как есть, БЕЗ поиска по
          имени (например, из Boolean.new_edges после Union/Subtract/
          Intersect, или из edges_in_box/edges_near)
        Строки/кортежи и готовые Edge можно свободно смешивать в одном списке.
    radius : float
        Радиус скругления.

    МОЖНО делать НЕСКОЛЬКО последовательных вызовов Fillet на одном и
    том же extrude с разными группами рёбер и разными радиусами (например
    сначала вертикальные рёбра радиусом 2, затем верхний контур радиусом
    1) — find_edge сам находит актуальное положение рёбер даже после
    того, как предыдущий Fillet изменил геометрию у общих вершин.

    ВАЖНО про радиус: он должен быть ЗАМЕТНО МЕНЬШЕ, чем самая короткая
    из смежных с ребром размеров (высота детали, ширина грани и т.п.).
    Если radius >= высоты/толщины детали, в которой лежит ребро — NX,
    скорее всего, откажется строить скругление с ошибкой вида
    "невозможно ограничить грань скругления". Если это случилось —
    в СЛЕДУЮЩЕЙ попытке возьми радиус заметно меньше (например вдвое).

    ВАЖНО: если ДВЕ группы рёбер (например vertical_edges присоединённой
детали и рёбра шва) ДЕЛЯТ ОБЩИЕ ВЕРШИНЫ и скругляются ОДНИМ радиусом —
их нужно передать в ОДИН вызов Fillet(workPart, extrude, group1+group2,
radius), а НЕ в раздельные последовательные вызовы. Раздельные вызовы
на общих вершинах вызывают ошибку NX "Невозможно ограничить грань
скругления" — это не значит, что не хватает ещё одного ребра другого
типа, это значит, что рёбра нужно объединить в один вызов.
    """

    def __init__(
        self,
        workPart,
        extrude: Extrude,
        edges: list,
        radius: float
    ):

        self.workPart = workPart
        self.extrude = extrude
        self.edges = edges
        self.radius = radius

        if not edges:
            raise ValueError(
                "Fillet: передан пустой список рёбер - скруглять нечего. "
                "Если это результат Union/Subtract/Intersect, проверьте "
                "merged.new_edges - похоже, шов в этом месте не появился "
                "(например, если тела слились без видимого перепада)."
            )

        if radius <= 0:
            raise ValueError(f"Fillet: radius должен быть положительным, получено {radius}.")

        edge_objs = []

        for entry in edges:
            if hasattr(entry, "GetVertices"):
                # уже готовый NXOpen.Edge - искать по имени не нужно
                edge_objs.append(entry)
            elif isinstance(entry, tuple):
                name, profile_index = entry
                edge_objs.append(extrude.find_edge(name, profile_index))
            else:
                edge_objs.append(extrude.find_edge(entry, 0))

        builder = workPart.Features.CreateEdgeBlendBuilder(
            NXOpen.Features.Feature.Null
        )

        builder.Tolerance = 0.01

        collector = workPart.ScCollectors.CreateCollector()

        rule_options = workPart.ScRuleFactory.CreateRuleOptions()

        rule_options.SetSelectedFromInactive(False)

        rule = workPart.ScRuleFactory.CreateRuleEdgeDumb(
            edge_objs,
            rule_options
        )

        rule_options.Dispose()

        collector.ReplaceRules([rule], False)

        builder.AddChainset(collector, str(radius))

        self.feature = builder.CommitFeature()

        builder.Destroy()

