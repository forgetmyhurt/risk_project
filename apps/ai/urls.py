from django.urls import path
from . import views

app_name = "ai"

urlpatterns = [
    path("ai/predict/", views.predict_page, name="predict_page"),
    path("predict/", views.predict_page, name="predict_page_alias"),
    path("ai/predict/api/", views.predict_api, name="predict_api"),
    path("predict/api/", views.predict_api, name="predict_api_alias"),
    path("model/show/", views.model_show, name="model_show"),
    path("model/analyze/", views.model_analyze_api, name="model_analyze"),
    path("model/health/", views.model_health_api, name="model_health"),
]
