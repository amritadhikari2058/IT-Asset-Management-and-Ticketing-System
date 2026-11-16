"""Bounded dependency-graph traversal and impact analysis for the CMDB.

All traversals are bounded (depth + node caps) and cycle-safe. Relationship
direction semantics come from the explicit orientation map in models.py —
never inferred from the payload.
"""

from django.db.models import Q
from django.utils import timezone

from .models import (
    RELATIONSHIP_ORIENTATION,
    ConfigurationItem,
    ConfigurationItemRelationship,
    ServiceConfigurationItemLink,
)

FORWARD_TYPES = frozenset(
    t for t, o in RELATIONSHIP_ORIENTATION.items() if o == "forward"
)
REVERSE_TYPES = frozenset(
    t for t, o in RELATIONSHIP_ORIENTATION.items() if o == "reverse"
)
SYMMETRIC_TYPES = frozenset(
    t for t, o in RELATIONSHIP_ORIENTATION.items() if o == "symmetric"
)
NEUTRAL_TYPES = frozenset(
    t for t, o in RELATIONSHIP_ORIENTATION.items() if o == "neutral"
)

DEFAULT_MAX_DEPTH = 5
ABS_MAX_DEPTH = 10
MAX_GRAPH_NODES = 200
MAX_AFFECTED_CIS = 500
MAX_CYCLE_WALK = 5_000
VERIFICATION_THRESHOLD_DAYS = 90

GRAPH_STATUSES = ("active", "proposed")
IMPACT_STATUSES = ("active",)

RETIRED_STATUSES = ("retired", "disposed")

ACTIVE_CHANGE_STATUSES = (
    "draft", "submitted", "risk_assessment", "technical_review",
    "pending_approval", "approved", "scheduled", "in_progress",
    "validation", "pir_required", "on_hold",
)


def clamp_depth(depth, default=DEFAULT_MAX_DEPTH, max_depth=ABS_MAX_DEPTH):
    try:
        depth = int(depth)
    except (TypeError, ValueError):
        depth = default
    if depth < 1:
        depth = 1
    if depth > max_depth:
        depth = max_depth
    return depth


def _as_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or "").lower() in ("1", "true", "yes", "on")


def _rel_filter_for_direction(ids, direction):
    """Q filter for one BFS hop.

    direction="downstream": CIs that depend on any CI in `ids`.
    direction="upstream":   CIs that any CI in `ids` depends on.
    """
    ids = list(ids)
    if direction == "downstream":
        # forward edge: target in ids -> source depends on target
        # reverse edge: source in ids -> target depends on source
        return (
            Q(target_ci_id__in=ids, relationship_type__in=FORWARD_TYPES)
            | Q(source_ci_id__in=ids, relationship_type__in=REVERSE_TYPES)
            | Q(
                source_ci_id__in=ids,
                relationship_type__in=SYMMETRIC_TYPES,
            )
            | Q(
                target_ci_id__in=ids,
                relationship_type__in=SYMMETRIC_TYPES,
            )
        )
    # upstream: what ids depend on
    return (
        Q(source_ci_id__in=ids, relationship_type__in=FORWARD_TYPES)
        | Q(target_ci_id__in=ids, relationship_type__in=REVERSE_TYPES)
        | Q(
            source_ci_id__in=ids,
            relationship_type__in=SYMMETRIC_TYPES,
        )
        | Q(
            target_ci_id__in=ids,
            relationship_type__in=SYMMETRIC_TYPES,
        )
    )


def _collect_other_end(relationship, ids, direction):
    """Given a relationship touching `ids`, return the far-end CI ids."""
    out = set()
    if direction == "downstream":
        if (
            relationship.relationship_type in FORWARD_TYPES
            and relationship.target_ci_id in ids
        ):
            out.add(relationship.source_ci_id)
        if (
            relationship.relationship_type in REVERSE_TYPES
            and relationship.source_ci_id in ids
        ):
            out.add(relationship.target_ci_id)
        if relationship.relationship_type in SYMMETRIC_TYPES:
            if relationship.source_ci_id in ids:
                out.add(relationship.target_ci_id)
            if relationship.target_ci_id in ids:
                out.add(relationship.source_ci_id)
    else:
        if (
            relationship.relationship_type in FORWARD_TYPES
            and relationship.source_ci_id in ids
        ):
            out.add(relationship.target_ci_id)
        if (
            relationship.relationship_type in REVERSE_TYPES
            and relationship.target_ci_id in ids
        ):
            out.add(relationship.source_ci_id)
        if relationship.relationship_type in SYMMETRIC_TYPES:
            if relationship.source_ci_id in ids:
                out.add(relationship.target_ci_id)
            if relationship.target_ci_id in ids:
                out.add(relationship.source_ci_id)
    return out


def _traverse(start_ids, direction, max_depth=DEFAULT_MAX_DEPTH,
              limit=MAX_GRAPH_NODES, statuses=IMPACT_STATUSES):
    """Bounded BFS. Returns (visited_set, truncated_bool)."""
    max_depth = clamp_depth(max_depth)
    visited = set(start_ids)
    frontier = set(start_ids)
    truncated = False
    for _ in range(max_depth):
        if not frontier:
            break
        rels = (
            ConfigurationItemRelationship.objects.filter(
                _rel_filter_for_direction(frontier, direction),
                status__in=statuses,
                is_deleted=False,
            )
            .values_list(
                "id", "source_ci_id", "target_ci_id", "relationship_type",
            )
        )
        nxt = set()
        for _rel_id, src_id, tgt_id, _rtype in rels:
            far = _collect_other_end(
                _RelView(src_id, tgt_id, _rtype), frontier, direction,
            )
            for ci_id in far:
                if ci_id in visited:
                    continue
                if len(visited) >= limit:
                    truncated = True
                    break
                visited.add(ci_id)
                nxt.add(ci_id)
            if truncated:
                break
        frontier = nxt
        if truncated:
            break
    return visited, truncated


class _RelView:
    """Minimal stand-in for a relationship row during traversal."""

    __slots__ = ("source_ci_id", "target_ci_id", "relationship_type")

    def __init__(self, source_ci_id, target_ci_id, relationship_type):
        self.source_ci_id = source_ci_id
        self.target_ci_id = target_ci_id
        self.relationship_type = relationship_type


def get_upstream_dependencies(ci, max_depth=DEFAULT_MAX_DEPTH,
                              limit=MAX_GRAPH_NODES):
    """CIs that `ci` depends on (bounded)."""
    ids, truncated = _traverse([ci.id], "upstream", max_depth, limit)
    ids.discard(ci.id)
    return ids, truncated


def get_downstream_dependents(ci, max_depth=DEFAULT_MAX_DEPTH,
                              limit=MAX_GRAPH_NODES):
    """CIs that depend on `ci` (bounded) — what breaks if `ci` fails."""
    ids, truncated = _traverse([ci.id], "downstream", max_depth, limit)
    ids.discard(ci.id)
    return ids, truncated


def _node_payload(ci):
    type_name = ""
    if getattr(ci, "ci_type_id", None) and hasattr(ci, "ci_type"):
        type_name = ci.ci_type.name if ci.ci_type else ""
    return {
        "id": ci.id,
        "ci_number": ci.ci_number,
        "name": ci.name,
        # frontend reads both `type` and `ci_type` as the type name
        "type": type_name,
        "ci_type": type_name,
        "ci_type_id": ci.ci_type_id,
        "status": ci.status,
        "criticality": ci.criticality,
        "environment": ci.environment,
        "department": ci.department_id,
        "owner": ci.owner_id,
        "updated_at": ci.updated_at.isoformat() if ci.updated_at else None,
    }


def build_dependency_graph(ci, view="combined", max_depth=DEFAULT_MAX_DEPTH,
                           max_nodes=MAX_GRAPH_NODES):
    """Graph payload for the dependency-map endpoint."""
    view = view if view in ("upstream", "downstream", "combined") else "combined"
    max_depth = clamp_depth(max_depth)

    visited = {ci.id}
    truncated = False
    if view in ("upstream", "combined"):
        up, trunc_up = _traverse(
            [ci.id], "upstream", max_depth, max_nodes, statuses=GRAPH_STATUSES,
        )
        visited |= up
        truncated = truncated or trunc_up
    if view in ("downstream", "combined"):
        down, trunc_down = _traverse(
            [ci.id], "downstream", max_depth, max_nodes,
            statuses=GRAPH_STATUSES,
        )
        visited |= down
        truncated = truncated or trunc_down

    if len(visited) > max_nodes:
        visited = set(sorted(visited)[:max_nodes])
        truncated = True

    cis_by_id = {
        c.id: c
        for c in ConfigurationItem.objects.filter(id__in=visited).select_related(
            "ci_type", "department", "owner",
        )
    }
    nodes = [_node_payload(cis_by_id[cid]) for cid in sorted(visited)]

    edge_rows = (
        ConfigurationItemRelationship.objects.filter(
            source_ci_id__in=visited,
            target_ci_id__in=visited,
            status__in=GRAPH_STATUSES,
            is_deleted=False,
        )
        .select_related("source_ci", "target_ci")
        .order_by("id")[: max_nodes * 2]
    )
    edges = []
    for rel in edge_rows:
        edges.append({
            "id": rel.id,
            "source": rel.source_ci_id,
            "target": rel.target_ci_id,
            "relationship_type": rel.relationship_type,
            "status": rel.status,
            "confidence": rel.confidence,
            "source_ci_number": rel.source_ci.ci_number,
            "target_ci_number": rel.target_ci.ci_number,
        })

    has_cycle = detect_relationship_cycles(node_ids=set(visited)) > 0
    return {
        "nodes": nodes,
        "edges": edges,
        "nodeCount": len(nodes),
        "edgeCount": len(edges),
        "cycleIndicator": "cycle" if has_cycle else None,
        "truncated": truncated,
        "max_depth": max_depth,
        "view": view,
    }


def detect_relationship_cycles(node_ids=None, limit=MAX_CYCLE_WALK):
    """Count structural cycles in the active relationship graph.

    When `node_ids` is given, only edges touching that subgraph are walked.
    Returns the number of distinct cycles found (bounded).
    """
    qs = ConfigurationItemRelationship.objects.filter(
        status="active", is_deleted=False,
    )
    if node_ids is not None:
        qs = qs.filter(
            source_ci_id__in=node_ids, target_ci_id__in=node_ids,
        )
    adjacency = {}
    rows = qs.values_list("source_ci_id", "target_ci_id")[:limit]
    for src_id, tgt_id in rows:
        adjacency.setdefault(src_id, set()).add(tgt_id)

    cycles = 0
    visited_global = set()
    WHITE, GREY, BLACK = 0, 1, 2
    color = {}

    for start in list(adjacency):
        if color.get(start, WHITE) != WHITE:
            continue
        stack = [(start, iter(sorted(adjacency.get(start, ()))))]
        color[start] = GREY
        visited_global.add(start)
        while stack:
            node, it = stack[-1]
            advanced = False
            for nbr in it:
                state = color.get(nbr, WHITE)
                if state == GREY:
                    cycles += 1
                    if cycles >= 100:
                        return cycles
                elif state == WHITE:
                    color[nbr] = GREY
                    stack.append((nbr, iter(sorted(adjacency.get(nbr, ())))))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                stack.pop()
    return cycles


def find_orphan_configuration_items():
    """CIs with no active relationships and no service links."""
    with_rels = ConfigurationItemRelationship.objects.filter(
        is_deleted=False, status="active",
    ).values_list("source_ci_id", flat=True)
    with_rels_target = ConfigurationItemRelationship.objects.filter(
        is_deleted=False, status="active",
    ).values_list("target_ci_id", flat=True)
    linked = set(with_rels) | set(with_rels_target)
    with_services = set(
        ServiceConfigurationItemLink.objects.filter(
            is_deleted=False,
        ).values_list("configuration_item_id", flat=True)
    )
    return ConfigurationItem.objects.filter(
        is_deleted=False,
    ).exclude(
        status__in=RETIRED_STATUSES,
    ).exclude(
        id__in=linked | with_services,
    ).order_by("ci_number")


def find_unverified_configuration_items(days=VERIFICATION_THRESHOLD_DAYS):
    """CIs never verified or verified longer than `days` ago."""
    cutoff = timezone.now() - timezone.timedelta(days=days)
    return ConfigurationItem.objects.filter(
        is_deleted=False,
    ).exclude(
        status__in=RETIRED_STATUSES,
    ).filter(
        Q(last_verified_at__isnull=True) | Q(last_verified_at__lt=cutoff),
    ).select_related("ci_type", "department", "owner", "technical_owner")


def verification_status_for(ci, days=VERIFICATION_THRESHOLD_DAYS):
    if ci.last_verified_at is None:
        return "never_verified"
    cutoff = timezone.now() - timezone.timedelta(days=days)
    if ci.last_verified_at < cutoff:
        return "overdue"
    return "verified"


def find_single_points_of_failure(service=None, include_retired=False):
    """Required service CIs without a redundancy peer.

    A CI is a single point of failure for a service when it is linked as
    required and no other CI shares its redundancy group for that service.
    """
    links = ServiceConfigurationItemLink.objects.filter(
        is_deleted=False, is_required=True,
    ).select_related("service", "configuration_item")
    if service is not None:
        links = links.filter(service=service)

    groups = {}
    for link in links:
        key = (link.service_id, link.redundancy_group or f"\x00{link.id}")
        groups.setdefault(key, []).append(link)

    spof = []
    for (service_id, group_key), members in groups.items():
        if group_key.startswith("\x00"):
            # no redundancy group: single member by definition
            unique_members = members
        else:
            active_cis = {
                m.configuration_item_id
                for m in members
                if include_retired
                or m.configuration_item.status not in RETIRED_STATUSES
            }
            unique_members = [m for m in members if len(active_cis) <= 1]
        for link in unique_members:
            ci = link.configuration_item
            spof.append({
                "service_id": service_id,
                "service_name": link.service.name,
                "ci_id": ci.id,
                "ci_number": ci.ci_number,
                "ci_name": ci.name,
                "role": link.role,
                "criticality": link.criticality,
                "redundancy_group": link.redundancy_group,
            })
    return spof


def analyze_ci_impact(ci, proposed_status=None, max_depth=DEFAULT_MAX_DEPTH,
                      include_tickets=False, include_changes=False,
                      limit=MAX_AFFECTED_CIS):
    """Full impact payload for a CI (spec: impact analysis endpoint)."""
    max_depth = clamp_depth(max_depth)
    affected_ids, truncated = _traverse(
        [ci.id], "downstream", max_depth, limit,
    )
    affected_ids.discard(ci.id)

    affected_qs = ConfigurationItem.objects.filter(
        id__in=affected_ids,
    ).select_related("ci_type", "department", "owner", "technical_owner")
    affected = list(affected_qs.order_by("ci_number"))

    departments = {}
    owners = {}
    for item in affected:
        if item.department_id:
            departments[item.department_id] = {
                "id": item.department_id,
                "name": item.department.name,
            }
        if item.owner_id:
            owners[item.owner_id] = {
                "id": item.owner_id,
                "username": item.owner.username,
                "email": item.owner.email,
            }
        if item.technical_owner_id and item.technical_owner_id not in owners:
            owners[item.technical_owner_id] = {
                "id": item.technical_owner_id,
                "username": item.technical_owner.username,
                "email": item.technical_owner.email,
            }

    affected_ci_ids = sorted(
        ConfigurationItem.objects.filter(id__in=affected_ids)
        .values_list("id", flat=True)
    )

    # Direct critical/high dependencies of the source CI
    critical_dependencies = []
    upstream_rels = ConfigurationItemRelationship.objects.filter(
        source_ci_id=ci.id, status="active", is_deleted=False,
    ).select_related("target_ci")
    for rel in upstream_rels:
        if rel.target_ci.criticality in ("critical", "high"):
            critical_dependencies.append({
                "ci_id": rel.target_ci_id,
                "ci_number": rel.target_ci.ci_number,
                "ci_name": rel.target_ci.name,
                "relationship_type": rel.relationship_type,
                "criticality": rel.target_ci.criticality,
                "status": rel.target_ci.status,
            })

    # Services touched: via service links on the source CI and affected CIs
    touched_ci_ids = set(affected_ci_ids) | {ci.id}
    service_links = ServiceConfigurationItemLink.objects.filter(
        configuration_item_id__in=touched_ci_ids, is_deleted=False,
    ).select_related("service")
    services = {}
    for link in service_links:
        services[link.service_id] = {
            "id": link.service_id,
            "name": link.service.name,
        }

    spof = find_single_points_of_failure()
    involved_spof = [
        s for s in spof if s["ci_id"] in touched_ci_ids
    ]

    affected_tickets = []
    if include_tickets:
        from tickets.models import Ticket

        from .models import ConfigurationItemTicketLink

        ticket_ids = set(
            ConfigurationItemTicketLink.objects.filter(
                configuration_item_id__in=touched_ci_ids, is_deleted=False,
            ).values_list("ticket_id", flat=True)
        )
        terminal = {"resolved", "closed", "archived", "cancelled", "merged"}
        for ticket in Ticket.objects.filter(id__in=ticket_ids).exclude(
            status__in=terminal,
        )[:200]:
            affected_tickets.append({
                "id": ticket.id,
                "title": ticket.title,
                "status": ticket.status,
                "priority": ticket.priority,
            })

    affected_changes = []
    if include_changes:
        from changes.models import ChangeRequest

        from .models import ConfigurationItemChangeLink

        change_ids = set(
            ConfigurationItemChangeLink.objects.filter(
                configuration_item_id__in=touched_ci_ids, is_deleted=False,
            ).values_list("change_id", flat=True)
        )
        now = timezone.now()
        for change in ChangeRequest.objects.filter(id__in=change_ids).filter(
            Q(status__in=ACTIVE_CHANGE_STATUSES) | Q(planned_start__gte=now),
        )[:200]:
            affected_changes.append({
                "id": change.id,
                "change_number": change.change_number,
                "title": change.title,
                "status": change.status,
                "planned_start": (
                    change.planned_start.isoformat()
                    if change.planned_start else None
                ),
            })

    # Risk summary
    critical_affected = sum(
        1 for item in affected if item.criticality in ("critical", "high")
    )
    production_affected = sum(
        1 for item in affected if item.environment == "production"
    )
    risky_proposal = proposed_status in (
        "retired", "disposed", "failed", "inactive",
    )
    parts = []
    if risky_proposal:
        parts.append(
            f"Moving {ci.ci_number} to '{proposed_status}' impacts "
            f"{len(affected)} dependent CI(s)"
        )
    else:
        parts.append(
            f"Analysis for {ci.ci_number} (status: {proposed_status or 'current'})"
            f" finds {len(affected)} dependent CI(s)"
        )
    parts.append(f"{critical_affected} high/critical")
    parts.append(f"{production_affected} in production")
    parts.append(f"{len(services)} service(s) touched")
    if involved_spof:
        parts.append(f"{len(involved_spof)} single point(s) of failure involved")
    if truncated:
        parts.append("result exceeds depth limit")
    risk_summary = ", ".join(parts) + "."

    payload = {
        # source CI top-level fields (frontend treats response as source CI)
        "id": ci.id,
        "ci_number": ci.ci_number,
        "name": ci.name,
        "status": ci.status,
        "criticality": ci.criticality,
        "environment": ci.environment,
        "ci_type": ci.ci_type_id,
        "ci_type_name": ci.ci_type.name if ci.ci_type_id else "",
        "department": ci.department_id,
        "owner": ci.owner_id,
        "last_verified_at": (
            ci.last_verified_at.isoformat() if ci.last_verified_at else None
        ),
        "record_version": ci.record_version,
        # impact result
        "affected_ci_ids": affected_ci_ids,
        "affected_count": len(affected_ci_ids),
        "affected_services": sorted(
            services.values(), key=lambda s: s["name"],
        ),
        "affected_departments": sorted(
            departments.values(), key=lambda d: d["name"],
        ),
        "affected_owners": sorted(
            owners.values(), key=lambda o: o["username"] or "",
        ),
        "critical_dependencies": critical_dependencies,
        "single_points_of_failure": involved_spof,
        "affected_tickets": affected_tickets,
        "affected_changes": affected_changes,
        "risk_summary": risk_summary,
        "proposed_status": proposed_status or "",
        "max_depth": max_depth,
        "truncated": truncated,
        "warning": "result exceeds depth limit" if truncated else "",
    }
    return payload


def get_service_dependency_graph(service, max_depth=DEFAULT_MAX_DEPTH,
                                 max_nodes=MAX_GRAPH_NODES):
    """Dependency graph rooted at all CIs linked to a service."""
    root_ids = list(
        ServiceConfigurationItemLink.objects.filter(
            service=service, is_deleted=False,
        ).values_list("configuration_item_id", flat=True)[:50]
    )
    if not root_ids:
        return {
            "nodes": [], "edges": [], "nodeCount": 0, "edgeCount": 0,
            "cycleIndicator": None, "truncated": False,
            "max_depth": clamp_depth(max_depth),
        }

    max_depth = clamp_depth(max_depth)
    visited = set(root_ids)
    frontier = set(root_ids)
    truncated = False
    for _ in range(max_depth):
        if not frontier or len(visited) >= max_nodes:
            break
        rels = ConfigurationItemRelationship.objects.filter(
            Q(source_ci_id__in=frontier) | Q(target_ci_id__in=frontier),
            status__in=GRAPH_STATUSES,
            is_deleted=False,
        ).values_list("id", "source_ci_id", "target_ci_id")
        nxt = set()
        for _rid, src_id, tgt_id in rels:
            for cid in (src_id, tgt_id):
                if cid in visited:
                    continue
                if len(visited) >= max_nodes:
                    truncated = True
                    break
                visited.add(cid)
                nxt.add(cid)
        frontier = nxt
    if len(visited) > max_nodes:
        visited = set(sorted(visited)[:max_nodes])
        truncated = True

    cis_by_id = {
        c.id: c
        for c in ConfigurationItem.objects.filter(id__in=visited).select_related(
            "ci_type",
        )
    }
    nodes = [_node_payload(cis_by_id[cid]) for cid in sorted(visited)]
    edges = []
    for rel in ConfigurationItemRelationship.objects.filter(
        source_ci_id__in=visited, target_ci_id__in=visited,
        status__in=GRAPH_STATUSES, is_deleted=False,
    ).select_related("source_ci", "target_ci").order_by("id")[: max_nodes * 2]:
        edges.append({
            "id": rel.id,
            "source": rel.source_ci_id,
            "target": rel.target_ci_id,
            "relationship_type": rel.relationship_type,
            "status": rel.status,
            "source_ci_number": rel.source_ci.ci_number,
            "target_ci_number": rel.target_ci.ci_number,
        })
    has_cycle = detect_relationship_cycles(node_ids=visited) > 0
    return {
        "nodes": nodes,
        "edges": edges,
        "nodeCount": len(nodes),
        "edgeCount": len(edges),
        "cycleIndicator": "cycle" if has_cycle else None,
        "truncated": truncated,
        "max_depth": max_depth,
    }
