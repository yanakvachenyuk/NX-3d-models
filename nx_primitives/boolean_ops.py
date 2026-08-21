"""Boolean ops (из original solid.py)."""
from __future__ import annotations

import NXOpen

def _as_bodies(obj):
    """
    Приводит что угодно к списку NXOpen.Body:
    - готовое тело NXOpen.Body -> [тело]
    - объект с атрибутом .body (Extrude, Boolean, ...) -> [obj.body]
    - список/кортеж таких объектов -> объединяет рекурсивно
    """
    if isinstance(obj, (list, tuple)):
        result = []
        for o in obj:
            result.extend(_as_bodies(o))
        return result
    if hasattr(obj, "body"):
        return [obj.body]
    return [obj]


def _mark_suppressed(obj, merged_body):
    """
    Помечает Extrude/Boolean-подобный объект (и вложенные списки/кортежи)
    как поглощённый (suppressed) результатом булевой операции, и
    запоминает результирующее тело.

    ЗАЧЕМ: после Union/Subtract/Intersect тела, переданные как `tools`,
    физически поглощаются в target и становятся SUPPRESSED в NX - любой
    последующий body.GetEdges() на них падает с NXException. Если после
    этого кто-то (например сгенерированный код) всё равно вызовет
    Fillet(workPart, tools_object, [...]) или tools_object.find_edge(...),
    Extrude.find_edge увидит self._suppressed=True и САМ прозрачно
    переключится на поиск ребра по сохранённым координатам вершин на
    self._merged_body (эквивалент edges_after_boolean(...)), вместо
    падения с малопонятной ошибкой NX.

    Это ТОЛЬКО подстраховка на случай ошибки в вызывающем коде -
    правильный способ по-прежнему: либо делать Fillet на tools ДО
    булевой операции, либо явно использовать edges_on()/
    edges_after_boolean()/attachment_seam() после неё.
    """
    if isinstance(obj, (list, tuple)):
        for o in obj:
            _mark_suppressed(o, merged_body)
        return
    if hasattr(obj, "body"):
        obj._suppressed = True
        obj._merged_body = merged_body


def _edge_signature(edge):
    vs = edge.GetVertices()
    if len(vs) != 2:
        return None
    p1 = (round(vs[0].X, 3), round(vs[0].Y, 3), round(vs[0].Z, 3))
    p2 = (round(vs[1].X, 3), round(vs[1].Y, 3), round(vs[1].Z, 3))
    return frozenset([p1, p2])


def _edge_signatures(bodies):
    sigs = set()
    for body in bodies:
        for edge in body.GetEdges():
            sig = _edge_signature(edge)
            if sig:
                sigs.add(sig)
    return sigs


class Boolean:
    """
    Булева операция над телами: объединение, вычитание, пересечение.

    После выполнения доступны:
        self.body                - результирующее тело
        self.new_edges           - список рёбер (NXOpen.Edge), появившихся
                                    ИМЕННО от этой операции - т.е. шов. Их
                                    не было ни у target, ни у tools ДО
                                    операции. Передавайте сразу в Fillet(...)
                                    - без всяких координат.
        self.removed_edges_count - сколько рёбер пропало (для справки/
                                    отладки, например если общая грань
                                    исчезла)

    ВАЖНО (частый источник ошибок): сразу ПОСЛЕ этой операции тело(а),
    переданные как `tools`, становятся SUPPRESSED - NX физически
    поглощает их в target. Это означает:
      - tools.body.GetEdges() и всё, что на нём основано (find_edge,
        Fillet(workPart, tools, [...], radius)), больше не работает и
        падает с ошибкой NX "Операция, запрещенная на подавленном объекте".
      - Это касается ЛЮБЫХ рёбер tools, не только шва - в т.ч.
        tools.top_edges()/bottom_edges()/vertical_edges(), если их
        нужно скруглить ПОСЛЕ Union.
      - Если такие рёбра нужны - используйте
        tools.edges_on(merged.body, names) / edges_after_boolean(...) /
        attachment_seam(...) - они ищут рёбра по заранее сохранённым
        координатам НА РЕЗУЛЬТИРУЮЩЕМ теле (merged.body), а не через
        само tools.body.
      - Либо сделайте нужный Fillet на tools ДО вызова Union/Subtract/
        Intersect, пока тело ещё активно.

    Начиная с этой версии tools-объекты (Extrude/Boolean с атрибутом
    .body) АВТОМАТИЧЕСКИ помечаются как suppressed сразу после операции
    (см. _mark_suppressed) - поэтому даже ошибочный вызов
    Fillet(workPart, tools, [...]) ПОСЛЕ этой операции больше не падает
    с NXException, а сам находит рёбра на результирующем теле через
    find_edge (см. Extrude.find_edge). Это подстраховка, а не замена
    правильному порядку вызовов.
    """

    _KIND_MAP = {
        "unite": NXOpen.Features.Feature.BooleanType.Unite,
        "subtract": NXOpen.Features.Feature.BooleanType.Subtract,
        "intersect": NXOpen.Features.Feature.BooleanType.Intersect,
    }

    def __init__(self, workPart, target, tools, kind="unite", tolerance=0.01):
        self.workPart = workPart
        self.kind = kind

        target_bodies = _as_bodies(target)
        tool_bodies = _as_bodies(tools)

        if not target_bodies:
            raise ValueError("Boolean: target не содержит ни одного тела.")
        if not tool_bodies:
            raise ValueError("Boolean: tools не содержит ни одного тела.")

        # запоминаем рёбра ДО операции, пока оба тела ещё существуют
        before_sigs = _edge_signatures(target_bodies) | _edge_signatures(tool_bodies)

        builder = workPart.Features.CreateBooleanBuilderUsingCollector(
            NXOpen.Features.BooleanFeature.Null
        )
        builder.Tolerance = tolerance
        builder.Operation = self._KIND_MAP[kind]

        rule_options_t = workPart.ScRuleFactory.CreateRuleOptions()
        rule_options_t.SetSelectedFromInactive(False)
        target_rule = workPart.ScRuleFactory.CreateRuleBodyDumb(
            target_bodies, True, rule_options_t
        )
        rule_options_t.Dispose()
        target_collector = workPart.ScCollectors.CreateCollector()
        target_collector.ReplaceRules([target_rule], False)
        builder.TargetBodyCollector = target_collector

        rule_options_k = workPart.ScRuleFactory.CreateRuleOptions()
        rule_options_k.SetSelectedFromInactive(False)
        tool_rule = workPart.ScRuleFactory.CreateRuleBodyDumb(
            tool_bodies, True, rule_options_k
        )
        rule_options_k.Dispose()
        tool_collector = workPart.ScCollectors.CreateCollector()
        tool_collector.ReplaceRules([tool_rule], False)
        builder.ToolBodyCollector = tool_collector

        builder.BooleanRegionSelect.AssignTargets(target_bodies)
        builder.BooleanRegionSelect.AssignTargets(tool_bodies)

        self.feature = builder.Commit()
        builder.Destroy()

        self.body = target_bodies[0] if target_bodies else None

        # сравниваем "было / стало" - без единой ручной координаты
        self.new_edges = []
        after_sigs = set()
        if self.body:
            for edge in self.body.GetEdges():
                sig = _edge_signature(edge)
                if sig:
                    after_sigs.add(sig)
                    if sig not in before_sigs:
                        self.new_edges.append(edge)

        self.removed_edges_count = len(before_sigs - after_sigs)

        # Подстраховка: tools стали suppressed - помечаем их как таковые,
        # чтобы find_edge на них (если его всё же вызовут по ошибке) сам
        # переключился на поиск по координатам на self.body, а не падал.
        _mark_suppressed(tools, self.body)


class Union(Boolean):
    def __init__(self, workPart, target, tools, *more_tools, tolerance=0.01):
        if more_tools:
            # Union(workPart, plate, wall_ab, wall_cd) → tools = [wall_ab, wall_cd]
            tools = [tools, *more_tools]
        super().__init__(workPart, target, tools, kind="unite", tolerance=tolerance)


class Subtract(Boolean):
    def __init__(self, workPart, target, tools, *more_tools, tolerance=0.01):
        if more_tools:
            tools = [tools, *more_tools]
        super().__init__(workPart, target, tools, kind="subtract", tolerance=tolerance)


class Intersect(Boolean):
    def __init__(self, workPart, target, tools, *more_tools, tolerance=0.01):
        if more_tools:
            tools = [tools, *more_tools]
        super().__init__(workPart, target, tools, kind="intersect", tolerance=tolerance)

