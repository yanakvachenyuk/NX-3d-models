"""Тонкостенное тело (Shell), из журнала NX 2406."""
from __future__ import annotations

import NXOpen

from .extrude_core import Extrude


class Shell:
    """
    Тонкостенное тело - убирает указанные грани и делает оболочку
    заданной толщины из остальных (Вставить->Смещение/масштаб->
    Тонкостенное тело).

    Parameters
    ----------
    extrude : Extrude
        Тело, из которого делается оболочка. extrude.body должен быть
        активным (не suppressed) - как и для Fillet/Chamfer.
    faces : list
        Грани, которые будут УДАЛЕНЫ (открыты) - например [extrude.top_face()]
        для открытой сверху коробки. Каждый элемент - готовый NXOpen.Face
        (получи через top_face()/bottom_face()/side_face()/circular_face()/
        face_from_edges()).
    thickness : float
        Толщина стенки (мм). Хранится СНАРУЖИ от исходных граней (как в
        журнале, ItemFlipFlag там был True) - материал добавляется наружу,
        внутренний объём остаётся исходного размера. Если понадобится
        противоположное направление - потребуется отдельно выставлять
        FlipFlag на каждой грани, здесь это не реализовано.
    """

    def __init__(
        self,
        workPart,
        extrude: Extrude,
        faces: list,
        thickness: float
    ):
        self.workPart = workPart
        self.extrude = extrude
        self.faces = faces
        self.thickness = thickness

        if not faces:
            raise ValueError(
                "Shell: не передано ни одной грани для удаления."
            )

        if thickness <= 0:
            raise ValueError(f"Shell: thickness должен быть положительным, получено {thickness}.")

        builder = workPart.Features.CreateShellBuilder(
            NXOpen.Features.Feature.Null
        )

        builder.Tolerance = 0.01
        builder.UseSurfaceApproximation = True
        builder.TgtPierceOption = False
        builder.SetDefaultThickness(str(thickness))

        collector = workPart.ScCollectors.CreateCollector()

        rule_options = workPart.ScRuleFactory.CreateRuleOptions()
        rule_options.SetSelectedFromInactive(False)

        rules = []
        for face in faces:
            rule = workPart.ScRuleFactory.CreateRuleFaceTangent(
                face, [], 0.5, rule_options
            )
            rules.append(rule)

        rule_options.Dispose()

        collector.ReplaceRules(rules, False)

        builder.RemovedFacesCollector = collector

        builder.Body = extrude.body

        self.feature = builder.Commit()

        builder.Destroy()