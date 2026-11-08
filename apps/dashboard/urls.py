from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("chart/enterprise/", views.chart_enterprise, name="chart_enterprise"),
    path("chart/risk/", views.chart_risk, name="chart_risk"),
    path("chart/compare/", views.chart_compare, name="chart_compare"),
]