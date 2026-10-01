"""Notifications: one fan-out feeding the in-app inbox and the email outbox
(docs/api/contract-phase3.md sections 3.2-3.8).

* :mod:`.fanout`: activity events (and new @mentions) -> notifications and outbox rows,
  in the same transaction as the event, per recipient preferences.
* :mod:`.access`: who may be told (``idea.view`` and each type's condition, through the
  policy), shared by the fan-out, the reminder scan and the worker's send-time check.
* :mod:`.preferences`: email mode per user and type (defaults in code).
* :mod:`.mentions`: parse, check and rewrite ``@[Name](user:<id>)`` tokens.
* :mod:`.inbox`: the bell's list, count and read state.
* :mod:`.unsubscribe`: signed one-click unsubscribe tokens.
* :mod:`.schedule`: the hourly job: evaluation reminders, daily digests, cleanup.

Nothing here ever reads or writes score data (role matrix section 3).
"""
