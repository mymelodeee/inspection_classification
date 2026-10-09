"""Signature-group support accounting (E06, C11): overlaps allowed, totals by unique event id."""


def summarize_groups(groups, bin_by_id):
    """groups: {name: iterable of event ids}; bin_by_id: {event id: bin} for all included events.

    Support counts are per group. The wafer-level total uses the union of ids, never the sum
    (naive_sum is reported only to show the difference). Unknown ids in a group are an error.
    """
    sets = {k: set(v) for k, v in groups.items()}
    unknown = {i for s in sets.values() for i in s} - set(bin_by_id)
    if unknown:
        raise ValueError(f"group support ids not in included events: {sorted(map(str, unknown))[:5]}")
    union = set().union(*sets.values()) if sets else set()
    names = list(sets)
    overlap = {i for i in union if sum(i in s for s in sets.values()) > 1}
    by_bin = {}
    for i in union:
        by_bin[bin_by_id[i]] = by_bin.get(bin_by_id[i], 0) + 1
    return {"support_counts": {k: len(v) for k, v in sets.items()},
            "naive_sum": sum(len(v) for v in sets.values()),
            "unique_union": len(union), "overlap_ids": sorted(overlap, key=str),
            "union_bin_counts": by_bin,
            "membership": {str(i): [k for k in names if i in sets[k]] for i in sorted(union, key=str)}}
