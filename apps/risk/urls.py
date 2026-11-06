from django.urls import path
from . import views

app_name = "risk"

urlpatterns = [
    path("risk/list/", views.risk_list, name="list"),
    path("risk/detail/<int:pk>/", views.risk_detail, name="detail"),
    path("risk/score/<int:pk>/", views.score_calc, name="score_calc"),
    path("report/<int:pk>/", views.risk_report, name="report"),
    path("report/<int:pk>/pdf/", views.report_pdf, name="report_pdf"),
]