from django.http import Http404
from django.shortcuts import render

from bustimes.formatting import format_timedelta

from .models import Journey
from .utils import get_stop_times


def journey_detail(request, base_version, idx):
    try:
        journey = (
            Journey.objects.filter(base_version_id=base_version, idx=idx)
            .select_related("pattern__line")
            .first()
        )
    except (ValueError, Journey.DoesNotExist):
        raise Http404

    if not journey:
        raise Http404

    stop_times = get_stop_times(journey)

    # Format times and add to each stop_time
    for st in stop_times:
        st.arrival_formatted = format_timedelta(st.arrival, plus_one=True)
        st.departure_formatted = format_timedelta(st.departure, plus_one=True)

    line = journey.pattern.line if journey.pattern else None
    line_name = line.service_line_no if line else ""

    return render(
        request,
        "tfl/journey_detail.html",
        {
            "journey": journey,
            "stop_times": stop_times,
            "line_name": line_name,
            "start_time": format_timedelta(journey.start_time, plus_one=True),
        },
    )
