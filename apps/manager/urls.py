from django.urls import path
from . import views

app_name = "manager"

urlpatterns = [
    path("manage/dashboard/", views.dashboard, name="dashboard"),
    path("manage/users/", views.user_list, name="users"),
    path("manage/threshold/", views.threshold_config, name="threshold"),
]
