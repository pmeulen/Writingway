"""
Small helpers for the MVP (Model-View-Presenter) refactor.

A Qt ``View`` widget wants to both subclass ``QWidget`` *and* implement an
``IView`` ``abc.ABC`` contract (see ``tasks/mvp.md`` §4).  Doing so directly
fails with::

    TypeError: metaclass conflict: the metaclass of a derived class must be a
    (non-strict) subclass of the metaclasses of all its bases

because ``QWidget``'s metaclass (``sip.wrappertype``) and ``ABCMeta`` are
unrelated.  This module provides a combined metaclass that subclasses both, so
a widget can inherit ``QWidget`` and an ``IView`` ABC at the same time.
"""
from __future__ import annotations

from abc import ABCMeta

from PyQt5.QtWidgets import QWidget


class QtWidgetABCMeta(type(QWidget), ABCMeta):  # type: ignore[misc]
    """Metaclass combining Qt's ``sip.wrappertype`` with ``ABCMeta``.

    Use this as the ``metaclass`` of a Qt View widget that also implements an
    ``IView`` ``abc.ABC``.
    """
