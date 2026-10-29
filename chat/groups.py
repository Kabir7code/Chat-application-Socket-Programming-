"""Group chat state (FR-004): which groups exist and who is in them.

Kept separate from the server so the rules can be tested on their own and
so group history (#18) can be added here later. Every method takes the same
lock, because many client threads create, join and leave groups at once.
Methods return copies of member lists, so callers can send messages after
the lock is released.
"""

import re
import threading

GROUP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,30}$")


class GroupError(Exception):
    """A group request that cannot be carried out. `code` goes back to the
    client in an error message."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class Group:
    def __init__(self, name, admin):
        self.name = name
        self.admin = admin
        self.members = [admin]  # in joining order; the admin is first


class GroupManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._groups = {}

    # ----------------------------------------------------------- helpers
    def _get(self, name):
        group = self._groups.get(name)
        if group is None:
            raise GroupError("GROUP_NOT_FOUND", f"Group '{name}' not found.")
        return group

    # ------------------------------------------------------------ actions
    def create(self, name, creator):
        """UC-03: create a group with the creator as its first member and admin."""
        name = str(name).strip()
        if not GROUP_NAME_PATTERN.match(name):
            raise GroupError(
                "INVALID_GROUP_NAME",
                "Group names must be 1-30 letters, digits, underscores or hyphens.",
            )
        with self._lock:
            if name in self._groups:
                raise GroupError("GROUP_EXISTS", "Group name already exists.")
            self._groups[name] = Group(name, creator)
            return [creator]

    def join(self, name, user):
        """UC-04: join an existing group. Returns the new member list."""
        with self._lock:
            group = self._get(name)
            if user in group.members:
                raise GroupError("ALREADY_MEMBER", f"You are already a member of '{name}'.")
            group.members.append(user)
            return list(group.members)

    def add(self, name, by, user):
        """UC-06: the group admin adds another user. Returns the new member list."""
        with self._lock:
            group = self._get(name)
            if by != group.admin:
                raise GroupError("NOT_GROUP_ADMIN", "Only the group admin can add members.")
            if user in group.members:
                raise GroupError("ALREADY_MEMBER", f"{user} is already a member of '{name}'.")
            group.members.append(user)
            return list(group.members)

    def leave(self, name, user):
        """UC-07: leave a group. Returns the members still in it.

        If the admin leaves, the longest-standing member becomes admin.
        A group with no members left is deleted.
        """
        with self._lock:
            group = self._get(name)
            if user not in group.members:
                raise GroupError("NOT_A_MEMBER", f"You are not a member of '{name}'.")
            return self._remove(group, user)

    def remove_user(self, user):
        """Take a user out of every group (used when they disconnect).

        Returns {group name: remaining members} for each group they were in.
        """
        with self._lock:
            return {
                group.name: self._remove(group, user)
                for group in list(self._groups.values())
                if user in group.members
            }

    def _remove(self, group, user):
        group.members.remove(user)
        if not group.members:
            del self._groups[group.name]
        elif group.admin == user:
            group.admin = group.members[0]
        return list(group.members)

    # ------------------------------------------------------------ queries
    def members(self, name):
        with self._lock:
            return list(self._get(name).members)

    def is_member(self, name, user):
        with self._lock:
            group = self._groups.get(name)
            return group is not None and user in group.members

    def admin(self, name):
        with self._lock:
            return self._get(name).admin

    def groups_of(self, user):
        with self._lock:
            return sorted(g.name for g in self._groups.values() if user in g.members)

    def names(self):
        with self._lock:
            return sorted(self._groups)
