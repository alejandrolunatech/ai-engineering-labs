"""In-memory employee directory."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Employee:
    id: str
    name: str
    email: str
    manager_id: str | None = None


class Directory:
    def __init__(self, employees: list[Employee]):
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]

    def find_manager(self, employee_id: str) -> Employee | None:
        """Return the employee's manager.

        Returns None for top-level employees (no manager_id) and when the
        manager has left and is no longer in the directory.
        """
        manager_id = self._by_id[employee_id].manager_id
        if manager_id is None:
            return None
        return self._by_id.get(manager_id)
