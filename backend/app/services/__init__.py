"""Application services: the use cases behind the routers.

Pattern (thin routers): a router parses the request, authorises with
:mod:`app.authz` (usually via :func:`app.authz.load_project` / ``require``), calls a
service, and returns a schema. Services take the request's ``AsyncSession`` (commit
happens after the route returns; raise to roll back) and the ``Principal``; they
never read roles themselves (use :mod:`app.authz`), and they emit activity
(:mod:`app.services.activity`) and audit entries (:mod:`app.services.audit`) in the
same transaction as the change.
"""
