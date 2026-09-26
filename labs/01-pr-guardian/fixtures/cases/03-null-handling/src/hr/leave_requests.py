"""Notifications for employee leave requests."""

from dataclasses import dataclass
from datetime import date

from hr.directory import Directory


@dataclass(frozen=True)
class LeaveRequest:
    employee_id: str
    start: date
    end: date


@dataclass(frozen=True)
class Notification:
    to: list[str]
    cc: list[str]
    subject: str


def build_notification(request: LeaveRequest, directory: Directory) -> Notification:
    employee = directory.get(request.employee_id)
    manager = directory.find_manager(request.employee_id)
    return Notification(
        to=[employee.email],
        cc=[manager.email],
        subject=f"Leave request {request.start:%Y-%m-%d} to {request.end:%Y-%m-%d}",
    )
