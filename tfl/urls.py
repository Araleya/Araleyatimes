from django.urls import path
from . import views

urlpatterns = [
    path("tfl/journeys/<int:base_version>/<int:idx>", views.journey_detail, name="tfl_journey_detail"),
]
