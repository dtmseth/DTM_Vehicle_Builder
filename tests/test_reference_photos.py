from __future__ import annotations

from dtm_buildsheet.domain.project_models import (
    BuildReferenceAsset,
    BuildReferenceAssignment,
    BuildUnit,
    IndividualUnit,
)
from dtm_buildsheet.domain.reference_photos import (
    invalid_reference_targets,
    publication_file_names,
    resolve_build_reference_photos,
)
from dtm_buildsheet.inputs.project_entry import new_project


def _assignment(scope: str, target_id: str = "", note: str = "", order: int = 0):
    return BuildReferenceAssignment(
        scope=scope, target_id=target_id, note=note, sort_order=order,
    )


def _project():
    return new_project(build_units=[
        BuildUnit(
            unit_id="group-1",
            individuals=[
                IndividualUnit(individual_id="vehicle-1"),
                IndividualUnit(individual_id="vehicle-2"),
            ],
        ),
        BuildUnit(
            unit_id="group-2",
            individuals=[IndividualUnit(individual_id="vehicle-3")],
        ),
    ])


def test_project_group_and_individual_scopes_resolve_for_one_vehicle():
    project = _project()
    project.reference_assets = [
        BuildReferenceAsset(
            reference_id="project-photo", file_name="a.jpg",
            assignments=[_assignment("project", note="all", order=2)],
        ),
        BuildReferenceAsset(
            reference_id="group-photo", file_name="b.jpg",
            assignments=[_assignment("unit_group", "group-1", note="group", order=1)],
        ),
        BuildReferenceAsset(
            reference_id="unit-photo", file_name="c.jpg",
            assignments=[_assignment("individual", "vehicle-1", note="unit", order=3)],
        ),
    ]

    resolved = resolve_build_reference_photos(
        project, unit_id="group-1", individual_id="vehicle-1",
    )

    assert [item.asset.reference_id for item in resolved] == [
        "group-photo", "project-photo", "unit-photo",
    ]
    assert [item.assignment.note for item in resolved] == ["group", "all", "unit"]


def test_more_specific_assignment_overrides_note_and_order_without_duplicate():
    project = _project()
    project.reference_assets = [BuildReferenceAsset(
        reference_id="shared", file_name="shared.jpg",
        assignments=[
            _assignment("project", note="general", order=8),
            _assignment("individual", "vehicle-1", note="special", order=1),
        ],
    )]

    resolved = resolve_build_reference_photos(
        project, unit_id="group-1", individual_id="vehicle-1",
    )

    assert len(resolved) == 1
    assert resolved[0].assignment.note == "special"
    assert resolved[0].assignment.sort_order == 1


def test_video_is_never_in_effective_generated_photo_set():
    project = _project()
    project.reference_assets = [BuildReferenceAsset(
        reference_id="video", file_name="walkaround.mov", media_type="video",
        assignments=[_assignment("project")],
    )]

    assert resolve_build_reference_photos(
        project, unit_id="group-1", individual_id="vehicle-1",
    ) == []


def test_assignments_for_other_groups_and_units_do_not_leak():
    project = _project()
    project.reference_assets = [
        BuildReferenceAsset(
            reference_id="other-group", file_name="a.jpg",
            assignments=[_assignment("unit_group", "group-2")],
        ),
        BuildReferenceAsset(
            reference_id="other-unit", file_name="b.jpg",
            assignments=[_assignment("individual", "vehicle-2")],
        ),
    ]

    assert resolve_build_reference_photos(
        project, unit_id="group-1", individual_id="vehicle-1",
    ) == []


def test_invalid_targets_are_reported_without_mutating_project():
    project = _project()
    project.reference_assets = [BuildReferenceAsset(
        reference_id="broken", file_name="broken.jpg",
        assignments=[
            _assignment("unit_group", "missing-group"),
            _assignment("individual", "missing-unit"),
        ],
    )]

    assert invalid_reference_targets(project) == [
        "broken: unknown unit group missing-group",
        "broken: unknown individual unit missing-unit",
    ]


def test_publication_names_are_safe_and_case_insensitively_unique():
    project = _project()
    project.reference_assets = [
        BuildReferenceAsset(
            reference_id="ref-one", file_name="Front:Grille.JPG",
            assignments=[_assignment("project", order=1)],
        ),
        BuildReferenceAsset(
            reference_id="ref-two", file_name="front_grille.jpg",
            assignments=[_assignment("project", order=2)],
        ),
    ]
    resolved = resolve_build_reference_photos(project, unit_id="group-1")
    assert publication_file_names(resolved) == [
        "Front_Grille.jpg",
        "front_grille-reftwo.jpg",
    ]
