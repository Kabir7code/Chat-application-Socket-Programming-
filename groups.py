"""Group chat state (FR-004): which groups exist and who is in them.

Kept separate from the server so the rules can be tested on their own.
Anyone who joins or is added later is shown the group's last HISTORY_SIZE
messages (FR-010, #18). With a database these come from the saved messages,
so they survive a restart (#61); without one they are kept in memory. Every method takes the same
lock, because many client threads create, join and leave groups at once.
Methods return copies of member lists, so callers can send messages after
the lock is released.

FR-013 (#51): if a MessageStore is given, every change (create, join, add,
leave, admin handover, delete) is saved to the database, and the saved
groups are loaded again when the server starts.
"""

import re
import threading
from collections import deque

GROUP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,30}$")
HISTORY_SIZE = 10  # recent messages kept per group (FR-010)


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
        self.history = deque(maxlen=HISTORY_SIZE)  # oldest first; old ones drop off


class GroupManager:
    def __init__(self, store=None):
        self._lock = threading.Lock()
        self._groups = {}
        self._store = store
        if store is not None:
            for name, (admin, members) in store.load_groups().items():
                if not members:
                    continue  # an empty group should never have been saved
                group = Group(name, admin)
                group.members = members
                self._groups[name] = group

    def _save(self, name):
        """Write one group's current state to the database (lock held)."""
        if self._store is None:
            return
        group = self._groups.get(name)
        if group is None:
            self._store.delete_group(name)
            # #61: a deleted group's messages go too, so a new group with
            # the same name does not show the old group's history
            self._store.delete_group_messages(name)
        else:
            self._store.save_group_state(group.name, group.admin, group.members)

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
            self._save(name)
            return [creator]

    def join(self, name, user):
        """UC-04: join an existing group. Returns the new member list."""
        with self._lock:
            group = self._get(name)
            if user in group.members:
                raise GroupError("ALREADY_MEMBER", f"You are already a member of '{name}'.")
            group.members.append(user)
            self._save(name)
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
            self._save(name)
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
        self._save(group.name)  # saves the new state, or deletes an empty group
        return list(group.members)

    # ----------------------------------------------------------- history
    def record(self, name, message):
        """FR-010: remember a group message for people who join later.
        With a database the server has already saved it there (#61), so
        only a GroupManager without one keeps it in memory."""
        if self._store is not None:
            return
        with self._lock:
            group = self._groups.get(name)
            if group is not None:
                group.history.append(dict(message))

    def history(self, name):
        """The group's recent messages, oldest first (copies).
        FR-010 (#61): read from the database when there is one, so the
        history survives a server restart."""
        with self._lock:
            group = self._groups.get(name)
            if group is None:
                return []
            if self._store is None:
                return [dict(m) for m in group.history]
        return self._store.group_messages(name, HISTORY_SIZE)

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
