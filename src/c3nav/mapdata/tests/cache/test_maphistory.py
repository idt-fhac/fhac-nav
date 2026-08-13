import io

import numpy as np
from django.test import SimpleTestCase
from shapely.geometry import box

from c3nav.mapdata.utils.cache.maphistory import MapHistory

UPDATE_A = (1, 100)
UPDATE_B = (2, 200)
UPDATE_C = (3, 300)


def make_history(updates, data, resolution=1, x=0, y=0):
    return MapHistory(updates=list(updates), resolution=resolution, x=x, y=y,
                      data=np.array(data, dtype=MapHistory.dtype))


def roundtrip(history):
    """write a history out and read it back, exactly like save()/open() do"""
    buf = io.BytesIO()
    history.write(buf)
    return MapHistory.read(io.BytesIO(buf.getvalue()))


class ReadOnlyArrayTests(SimpleTestCase):
    """
    Regression tests for #307. np.frombuffer() over the bytes returned by f.read() is always
    read-only, so anything read back from disk used to raise
    "ValueError: assignment destination is read-only" as soon as it was modified or saved again.
    """

    def setUp(self):
        self.history = roundtrip(make_history([UPDATE_A, UPDATE_B],
                                              [[0, 0, 0, 0],
                                               [0, 1, 1, 0],
                                               [0, 1, 1, 0],
                                               [0, 0, 0, 0]]))

    def test_data_read_from_a_file_is_writeable(self):
        self.assertTrue(self.history.data.flags.writeable)

    def test_a_history_read_from_a_file_can_be_written_again(self):
        # renderdata calls save_level() on a history it only opened, which goes
        # save() -> write() -> simplify(), and simplify() assigns to self.data
        self.history.write(io.BytesIO())

    def test_simplify_can_be_called_on_a_history_read_from_a_file(self):
        self.history.simplify()

    def test_add_geometry_works_on_a_history_read_from_a_file(self):
        self.history.add_geometry(box(0, 0, 2, 2), UPDATE_C)
        self.assertEqual(self.history.updates[-1], UPDATE_C)

    def test_composite_works_on_a_history_read_from_a_file(self):
        self.history.composite(roundtrip(make_history([UPDATE_C], [[0] * 4] * 4)), None)

    def test_values_survive_the_roundtrip(self):
        self.assertEqual(self.history.updates, [UPDATE_A, UPDATE_B])
        np.testing.assert_array_equal(self.history.data,
                                      [[0, 0, 0, 0],
                                       [0, 1, 1, 0],
                                       [0, 1, 1, 0],
                                       [0, 0, 0, 0]])


class SimplifyTests(SimpleTestCase):
    def test_unused_updates_are_dropped_and_cells_reindexed(self):
        history = make_history([UPDATE_A, UPDATE_B, UPDATE_C],
                               [[0, 0, 2, 2]] * 2)

        history.simplify()

        # UPDATE_B has no cells left, UPDATE_A is kept because index 0 always is
        self.assertEqual(history.updates, [UPDATE_A, UPDATE_C])
        np.testing.assert_array_equal(history.data, [[0, 0, 1, 1]] * 2)

    def test_the_first_update_is_kept_even_without_cells(self):
        history = make_history([UPDATE_A, UPDATE_B], [[1, 1]] * 2)

        history.simplify()

        self.assertEqual(history.updates, [UPDATE_A, UPDATE_B])
