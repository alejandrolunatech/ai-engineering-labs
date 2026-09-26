from datetime import date

from hr.directory import Directory, Employee
from hr.leave_requests import LeaveRequest, build_notification

DIRECTORY = Directory(
    [
        Employee("e-1", "Ada", "ada@example.com", manager_id="e-2"),
        Employee("e-2", "Grace", "grace@example.com", manager_id="e-3"),
        Employee("e-3", "Linus", "linus@example.com", manager_id="e-9"),
    ]
)


def test_notifies_employee():
    request = LeaveRequest("e-1", date(2026, 7, 1), date(2026, 7, 5))
    notification = build_notification(request, DIRECTORY)
    assert notification.to == ["ada@example.com"]
    assert notification.subject == "Leave request 2026-07-01 to 2026-07-05"


def test_ccs_manager():
    request = LeaveRequest("e-1", date(2026, 7, 1), date(2026, 7, 5))
    notification = build_notification(request, DIRECTORY)
    assert notification.cc == ["grace@example.com"]
