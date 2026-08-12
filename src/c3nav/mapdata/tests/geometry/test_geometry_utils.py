"""
Characterisation tests for c3nav.mapdata.utils.geometry.

These describe what the helpers currently do, including a few behaviours that
look surprising -- those are marked below. They are deliberately written
against observed behaviour rather than intent, so that a future refactor of
this module shows up as a diff here rather than as a silent change.

The helpers are pure geometry, so SimpleTestCase is enough and no database is
touched.
"""
from django.test import SimpleTestCase
from shapely.geometry import GeometryCollection, LinearRing, LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry import mapping as shapely_mapping

from c3nav.mapdata.utils.geometry import (WrappedGeometry, assert_multilinestring, assert_multipolygon, clean_geometry,
                                          cut_line_with_point, cut_polygon_with_line, get_rings,
                                          good_representative_point, smart_mapping, unwrap_geom)

SQUARE = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
SQUARE_WITH_HOLE = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)], [[(2, 2), (2, 8), (8, 8), (8, 2)]])
# a C, open towards +x, whose centroid falls in the notch and thus outside the polygon
C_SHAPE = Polygon([(0, 0), (10, 0), (10, 3), (3, 3), (3, 7), (10, 7), (10, 10), (0, 10)])


class AssertMultipolygonTests(SimpleTestCase):
    def test_polygon_is_wrapped_in_a_list(self):
        self.assertEqual(assert_multipolygon(SQUARE), [SQUARE])

    def test_multipolygon_is_unpacked(self):
        self.assertEqual(assert_multipolygon(MultiPolygon([SQUARE])), [SQUARE])

    def test_empty_geometries_give_an_empty_list(self):
        self.assertEqual(assert_multipolygon(GeometryCollection()), [])
        self.assertEqual(assert_multipolygon(Polygon()), [])

    def test_non_polygons_in_a_collection_are_dropped(self):
        collection = GeometryCollection([SQUARE, LineString([(0, 0), (1, 1)])])
        self.assertEqual(assert_multipolygon(collection), [SQUARE])


class AssertMultilinestringTests(SimpleTestCase):
    def test_linestring_is_wrapped_in_a_list(self):
        line = LineString([(0, 0), (1, 1)])
        self.assertEqual(assert_multilinestring(line), [line])

    def test_multilinestring_is_unpacked(self):
        line = LineString([(0, 0), (1, 1)])
        self.assertEqual(assert_multilinestring(MultiLineString([line])), [line])

    def test_empty_geometry_gives_an_empty_list(self):
        self.assertEqual(assert_multilinestring(GeometryCollection()), [])


class GetRingsTests(SimpleTestCase):
    def test_polygon_yields_exterior_and_interiors(self):
        self.assertEqual(len(tuple(get_rings(SQUARE))), 1)
        self.assertEqual(len(tuple(get_rings(SQUARE_WITH_HOLE))), 2)

    def test_multipolygon_yields_rings_of_every_member(self):
        self.assertEqual(len(tuple(get_rings(MultiPolygon([SQUARE, SQUARE_WITH_HOLE])))), 3)

    def test_linearring_yields_itself(self):
        ring = LinearRing([(0, 0), (1, 0), (1, 1)])
        self.assertEqual(tuple(get_rings(ring)), (ring, ))

    def test_geometry_without_rings_yields_nothing(self):
        self.assertEqual(tuple(get_rings(Point(0, 0))), ())


class GoodRepresentativePointTests(SimpleTestCase):
    def test_point_is_returned_unchanged(self):
        point = Point(3, 4)
        self.assertIs(good_representative_point(point), point)

    def test_convex_polygon_uses_its_centroid(self):
        self.assertEqual(good_representative_point(SQUARE), Point(5, 5))

    def test_concave_polygon_falls_back_to_a_point_inside(self):
        # the centroid of the C sits in the notch, so it must not be used
        self.assertFalse(C_SHAPE.contains(C_SHAPE.centroid))
        result = good_representative_point(C_SHAPE)
        self.assertEqual(result, Point(1.5, 5))
        self.assertTrue(C_SHAPE.contains(result))


class CleanGeometryTests(SimpleTestCase):
    def test_valid_geometry_is_returned_untouched(self):
        self.assertIs(clean_geometry(SQUARE), SQUARE)

    def test_self_intersecting_polygon_is_repaired(self):
        bowtie = Polygon([(0, 0), (10, 10), (10, 0), (0, 10)])
        self.assertFalse(bowtie.is_valid)
        cleaned = clean_geometry(bowtie)
        self.assertTrue(cleaned.is_valid)
        self.assertIsInstance(cleaned, Polygon)

    def test_repair_may_return_a_multipolygon_despite_the_docstring(self):
        # the docstring promises to only repair "if it results in a Polygon (not
        # MultiPolygon)", but the implementation returns buffer(0) unconditionally
        double_bowtie = Polygon([(0, 0), (4, 4), (8, 0), (8, 8), (4, 4), (0, 8)])
        self.assertFalse(double_bowtie.is_valid)
        cleaned = clean_geometry(double_bowtie)
        self.assertTrue(cleaned.is_valid)
        self.assertIsInstance(cleaned, MultiPolygon)


class WrappedGeometryTests(SimpleTestCase):
    def setUp(self):
        self.geojson = shapely_mapping(SQUARE)
        self.wrapped = WrappedGeometry(self.geojson)

    def test_it_impersonates_the_wrapped_type(self):
        # __class__ is overridden, so isinstance checks pass for the wrapped geometry
        self.assertIsInstance(self.wrapped, Polygon)

    def test_attributes_are_proxied(self):
        self.assertEqual(self.wrapped.area, 100.0)

    def test_unwrap_geom_returns_the_real_geometry(self):
        self.assertIsInstance(unwrap_geom(self.wrapped), Polygon)
        self.assertNotIsInstance(unwrap_geom(self.wrapped), WrappedGeometry)

    def test_unwrap_geom_passes_plain_geometries_through(self):
        self.assertIs(unwrap_geom(SQUARE), SQUARE)

    def test_smart_mapping_avoids_re_serialising(self):
        self.assertIs(smart_mapping(self.wrapped), self.geojson)
        self.assertEqual(smart_mapping(SQUARE), self.geojson)

    def test_empty_coordinates_give_an_empty_collection(self):
        empty = WrappedGeometry({'type': 'Polygon', 'coordinates': []})
        self.assertTrue(empty.wrapped_geom.is_empty)

    def test_it_survives_pickling(self):
        import pickle
        self.assertEqual(pickle.loads(pickle.dumps(self.wrapped)).area, 100.0)


class CutLineWithPointTests(SimpleTestCase):
    def setUp(self):
        self.line = LineString([(0, 0), (10, 0)])

    def test_cutting_in_the_middle_gives_two_parts(self):
        result = cut_line_with_point(self.line, Point(5, 0))
        self.assertEqual([tuple(part.coords) for part in result],
                         [((0.0, 0.0), (5.0, 0.0)), ((5.0, 0.0), (10.0, 0.0))])

    def test_points_at_or_beyond_the_ends_do_not_cut(self):
        for point in (Point(-5, 0), Point(0, 0), Point(10, 0), Point(15, 0)):
            with self.subTest(point=point):
                self.assertEqual(cut_line_with_point(self.line, point), (self.line, ))

    def test_a_point_off_the_line_is_not_projected_onto_it(self):
        # the cut position comes from project(), but the point is inserted verbatim,
        # so the two halves are not collinear with the original line
        result = cut_line_with_point(self.line, Point(5, 3))
        self.assertEqual([tuple(part.coords) for part in result],
                         [((0.0, 0.0), (5.0, 3.0)), ((5.0, 3.0), (10.0, 0.0))])


class CutPolygonWithLineTests(SimpleTestCase):
    def test_a_line_crossing_the_polygon_splits_it(self):
        result = cut_polygon_with_line(SQUARE, LineString([(5, -1), (5, 11)]))
        self.assertEqual(len(result), 2)
        self.assertEqual(sorted(round(part.area, 6) for part in result), [50.0, 50.0])

    def test_a_line_that_misses_leaves_the_polygon_alone(self):
        result = cut_polygon_with_line(SQUARE, LineString([(20, -1), (20, 11)]))
        self.assertEqual([round(part.area, 6) for part in result], [100.0])

    def test_a_line_ending_inside_does_not_cut(self):
        # a half-cut would be invalid geometry, so the polygon is returned as-is
        result = cut_polygon_with_line(SQUARE, LineString([(5, -1), (5, 5)]))
        self.assertEqual([round(part.area, 6) for part in result], [100.0])

    def test_a_line_running_along_an_edge_does_not_cut(self):
        result = cut_polygon_with_line(SQUARE, LineString([(0, -1), (0, 11)]))
        self.assertEqual([round(part.area, 6) for part in result], [100.0])

    def test_cutting_preserves_total_area(self):
        result = cut_polygon_with_line(SQUARE_WITH_HOLE, LineString([(5, -1), (5, 11)]))
        self.assertAlmostEqual(sum(part.area for part in result), SQUARE_WITH_HOLE.area)
