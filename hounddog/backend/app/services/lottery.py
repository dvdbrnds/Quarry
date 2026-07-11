"""Configurable lottery engine with pluggable strategies."""

import random as _random
from typing import Protocol

from ..models.permit_application import PermitApplication


class LotteryStrategy(Protocol):
    """Protocol for lottery selection strategies."""

    def rank(
        self,
        applications: list[PermitApplication],
        spots: int,
        seed: str | None = None,
    ) -> tuple[list[PermitApplication], list[PermitApplication]]:
        """Rank applications into selected and waitlisted groups.

        Returns:
            (selected, waitlisted) — selected up to `spots` count,
            remainder goes to waitlist in priority order.
        """
        ...


class SeniorityWeightedStrategy:
    """Weighted random draw where lower class_year (more senior) gets higher weight."""

    def rank(
        self,
        applications: list[PermitApplication],
        spots: int,
        seed: str | None = None,
    ) -> tuple[list[PermitApplication], list[PermitApplication]]:
        if not applications:
            return [], []

        rng = _random.Random(seed)

        max_year = max(a.class_year for a in applications)
        weights = [max_year - a.class_year + 1 for a in applications]

        selected: list[PermitApplication] = []
        pool = list(zip(applications, weights))

        pick_count = min(spots, len(pool))
        for _ in range(pick_count):
            if not pool:
                break
            apps_list, w_list = zip(*pool)
            chosen = rng.choices(list(apps_list), weights=list(w_list), k=1)[0]
            selected.append(chosen)
            pool = [(a, w) for a, w in pool if a.id != chosen.id]

        waitlisted = [a for a, _ in pool]
        waitlisted.sort(key=lambda a: a.class_year)

        return selected, waitlisted


class PureRandomStrategy:
    """Uniform random draw — every applicant has equal chance regardless of seniority."""

    def rank(
        self,
        applications: list[PermitApplication],
        spots: int,
        seed: str | None = None,
    ) -> tuple[list[PermitApplication], list[PermitApplication]]:
        if not applications:
            return [], []

        rng = _random.Random(seed)
        shuffled = list(applications)
        rng.shuffle(shuffled)

        pick_count = min(spots, len(shuffled))
        selected = shuffled[:pick_count]
        waitlisted = shuffled[pick_count:]

        return selected, waitlisted


class ClassPriorityStrategy:
    """Deterministic senior-first: seniors fill all spots before juniors get any.

    Within the same class year, selection is random.
    """

    def rank(
        self,
        applications: list[PermitApplication],
        spots: int,
        seed: str | None = None,
    ) -> tuple[list[PermitApplication], list[PermitApplication]]:
        if not applications:
            return [], []

        rng = _random.Random(seed)

        by_year: dict[int, list[PermitApplication]] = {}
        for app in applications:
            by_year.setdefault(app.class_year, []).append(app)

        selected: list[PermitApplication] = []
        waitlisted: list[PermitApplication] = []

        for year in sorted(by_year.keys()):
            group = by_year[year]
            rng.shuffle(group)

            remaining_spots = spots - len(selected)
            if remaining_spots <= 0:
                waitlisted.extend(group)
            elif len(group) <= remaining_spots:
                selected.extend(group)
            else:
                selected.extend(group[:remaining_spots])
                waitlisted.extend(group[remaining_spots:])

        return selected, waitlisted


class SeniorityTimestampStrategy:
    """Moravian's actual process: class year first, then application timestamp.

    No randomness. Seniors go first; within the same class year, whoever
    applied earliest wins. This is a deterministic first-come-first-served
    selection within each seniority tier.
    """

    def rank(
        self,
        applications: list[PermitApplication],
        spots: int,
        seed: str | None = None,
    ) -> tuple[list[PermitApplication], list[PermitApplication]]:
        if not applications:
            return [], []

        ordered = sorted(applications, key=lambda a: (a.class_year, a.created_at))

        pick_count = min(spots, len(ordered))
        selected = ordered[:pick_count]
        waitlisted = ordered[pick_count:]

        return selected, waitlisted


STRATEGIES: dict[str, LotteryStrategy] = {
    "seniority_weighted": SeniorityWeightedStrategy(),
    "pure_random": PureRandomStrategy(),
    "class_priority": ClassPriorityStrategy(),
    "seniority_timestamp": SeniorityTimestampStrategy(),
}


def get_strategy(name: str) -> LotteryStrategy:
    """Look up a strategy by name. Falls back to seniority_timestamp if unknown."""
    return STRATEGIES.get(name, STRATEGIES["seniority_timestamp"])


def distribute_capacity(total: int, lot_names: list[str]) -> dict[str, int]:
    """Distribute total capacity across lots, spreading remainder round-robin."""
    base = total // len(lot_names)
    remainder = total % len(lot_names)
    return {
        name: base + (1 if i < remainder else 0)
        for i, name in enumerate(lot_names)
    }


def assign_lots(
    selected: list[PermitApplication],
    lot_capacities: dict[str, int],
) -> list[str]:
    """Assign each selected applicant their highest-preference lot with remaining capacity.

    Returns a list of warnings (e.g., overflow assignments).
    Modifies applications in-place, setting `assigned_lot`.
    """
    warnings = []
    lot_counts: dict[str, int] = {lot: 0 for lot in lot_capacities}
    lot_order = list(lot_capacities.keys())

    for app in selected:
        preferences = app.lot_preferences if app.lot_preferences else lot_order
        assigned = False

        for pref in preferences:
            if pref in lot_counts and lot_counts[pref] < lot_capacities[pref]:
                app.assigned_lot = pref
                lot_counts[pref] += 1
                assigned = True
                break

        if not assigned:
            for lot in lot_order:
                if lot_counts[lot] < lot_capacities[lot]:
                    app.assigned_lot = lot
                    lot_counts[lot] += 1
                    assigned = True
                    break

        if not assigned:
            warnings.append(
                f"All lots at capacity. Applicant {app.id} could not be assigned a lot."
            )
            app.assigned_lot = lot_order[0]

    return warnings
