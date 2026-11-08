"""PostGIS operators (https://postgis.net/docs/reference.html#Operators).

Method names don't shadow peewee's: ``==`` stays SQL ``=`` and ``.contains()``
stays peewee's ``ILIKE``. Bounding-box equality is :meth:`SpatialOperators.same_bbox`.
"""

from typing import Any

import peewee as pw
import shapely

from .convert import context_srid, literal


def _rhs(lhs: object, rhs: Any) -> Any:
    return literal(rhs, srid=context_srid(lhs)) if isinstance(rhs, shapely.Geometry) else rhs


class SpatialOperators:
    """Mixin for geometry/geography valued nodes."""

    __slots__ = ()

    def _op(self, op: str, rhs: Any) -> pw.Expression:
        return pw.Expression(self, op, _rhs(self, rhs))

    # bounding box relations
    def bbox_overlaps(self, rhs: Any, *, nd: bool = False) -> pw.Expression:
        """``&&`` (``&&&`` with ``nd``): the bounding boxes intersect. Uses spatial indexes."""
        return self._op("&&&" if nd else "&&", rhs)

    def bbox_contains(self, rhs: Any) -> pw.Expression:
        """``~``: this bounding box contains ``rhs``'s."""
        return self._op("~", rhs)

    def bbox_within(self, rhs: Any) -> pw.Expression:
        """``@``: this bounding box is contained by ``rhs``'s."""
        return self._op("@", rhs)

    def same_bbox(self, rhs: Any) -> pw.Expression:
        """``~=``: the bounding boxes are the same."""
        return self._op("~=", rhs)

    def left_of(self, rhs: Any) -> pw.Expression:
        """``<<``: strictly left of."""
        return self._op("<<", rhs)

    def right_of(self, rhs: Any) -> pw.Expression:
        """``>>``: strictly right of."""
        return self._op(">>", rhs)

    def below(self, rhs: Any) -> pw.Expression:
        """``<<|``: strictly below."""
        return self._op("<<|", rhs)

    def above(self, rhs: Any) -> pw.Expression:
        """``|>>``: strictly above."""
        return self._op("|>>", rhs)

    def overleft(self, rhs: Any) -> pw.Expression:
        """``&<``: overlaps or is left of."""
        return self._op("&<", rhs)

    def overright(self, rhs: Any) -> pw.Expression:
        """``&>``: overlaps or is right of."""
        return self._op("&>", rhs)

    def overbelow(self, rhs: Any) -> pw.Expression:
        """``&<|``: overlaps or is below."""
        return self._op("&<|", rhs)

    def overabove(self, rhs: Any) -> pw.Expression:
        """``|&>``: overlaps or is above."""
        return self._op("|&>", rhs)

    # distances, for KNN ordering: .order_by(Model.geom.knn(point)).limit(10)
    def knn(self, rhs: Any) -> pw.Expression:
        """``<->``: 2D distance; index-assisted in ``ORDER BY``."""
        return self._op("<->", rhs)

    def bbox_distance(self, rhs: Any) -> pw.Expression:
        """``<#>``: 2D distance between bounding boxes."""
        return self._op("<#>", rhs)

    def knn_nd(self, rhs: Any) -> pw.Expression:
        """``<<->>``: n-D distance between bounding box centroids."""
        return self._op("<<->>", rhs)
