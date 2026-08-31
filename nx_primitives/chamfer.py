"""Фаска - через классический ChamferBuilder (по структуре ближе к Fillet,
чем к более новой ApexRangeChamferBuilder из записанного журнала)."""
from __future__ import annotations

import NXOpen

from .extrude_core import Extrude


class Chamfer:
    """
    Фаска с одним равным отступом (SingleOffset, 45 градусов) на рёбрах тела.

    Аналог Fillet: один SmartCollector на все переданные рёбра.

    Parameters
    ----------
    extrude : Extrude
        Как и в Fillet - нужен только для поиска рёбер-строк/кортежей
        по имени; для готовых NXOpen.Edge не используется.
    edges : list
        Как и в Fillet: строка "ab", кортеж ("ab", 1) или готовый
        NXOpen.Edge - можно смешивать.
    setback : float
        Отступ фаски (мм), одинаковый по обеим граням ребра.

    ПРИМЕЧАНИЕ: реализован только этот, симметричный тип (SymmetricOffsets -
    один отступ, одинаковый по обеим граням ребра). Два других варианта
    enum'а ChamferOption - TwoOffsets (два разных отступа) и
    OffsetAndAngle (отступ + угол) - сюда не добавлены; если понадобятся,
    поменяй builder.Option на нужное значение и, для OffsetAndAngle,
    задай ещё и builder.Angle аналогично FirstOffset ниже.
    """

    def __init__(
        self,
        workPart,
        extrude: Extrude,
        edges: list,
        setback: float
    ):
        self.workPart = workPart
        self.extrude = extrude
        self.edges = edges
        self.setback = setback

        if not edges:
            raise ValueError(
                "Chamfer: передан пустой список рёбер - фасковать нечего."
            )

        if setback <= 0:
            raise ValueError(f"Chamfer: setback должен быть положительным, получено {setback}.")
        
        edge_objs = []
        for entry in edges:
            if hasattr(entry, "GetVertices"):
                edge_objs.append(entry)
            elif isinstance(entry, tuple):
                name, profile_index = entry
                edge_objs.append(extrude.find_edge(name, profile_index))
            else:
                edge_objs.append(extrude.find_edge(entry, 0))

        builder = workPart.Features.CreateChamferBuilder(
            NXOpen.Features.Feature.Null
        )

        builder.Option = NXOpen.Features.ChamferBuilder.ChamferOption.SymmetricOffsets
        builder.Tolerance = 0.01

        builder.FirstOffset = str(setback)

        collector = workPart.ScCollectors.CreateCollector()

        rule_options = workPart.ScRuleFactory.CreateRuleOptions()
        rule_options.SetSelectedFromInactive(False)

        rule = workPart.ScRuleFactory.CreateRuleEdgeDumb(edge_objs, rule_options)

        rule_options.Dispose()

        collector.ReplaceRules([rule], False)

        builder.SmartCollector = collector

        self.feature = builder.CommitFeature()

        builder.Destroy()