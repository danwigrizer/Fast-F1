# import os
# os.environ['HOME'] = ''  # create HOME so we don't crash on import

from fastf1 import core, api
from matplotlib import pyplot as plt
import pandas as pd
import numpy as np
import datetime
from math import sqrt
import pickle
import IPython
import multiprocessing as mp
from itertools import product
import sys
import time
from scipy import stats

# core.utils.CACHE_PATH = 'D:\\Dateien\\FF1Data'  # set the correct cache path

# Event selection
YEAR = 2019
GP = 10
EVENT = 'R'

csv_name = '2019-10-5_track_map.csv'


def dump_track_points_to_csv(name):
    session = core.get_session(YEAR, GP, EVENT)
    pos = api.position(session.api_path)

    numbers = list(pos.keys())
    # create combined data frame with all column names but without data
    combined = pd.DataFrame(columns=['index', *pos[numbers[0]].columns])

    for n in numbers:
        tmp = pos[n].reset_index()
        combined = combined.append(tmp)

    # filter out data points where the car is not on track
    is_on_track = combined['Status'] == 'OnTrack'
    combined = combined[is_on_track]

    no_dupl_combined = combined.reset_index().filter(items=('X', 'Y')).drop_duplicates()

    no_dupl_combined.to_csv(name, index=False)


def track_points_from_csv(name):
    df = pd.read_csv(name)
    return df


class Point:
    """Simple point class
    offers x and y paramters as a function for calculating distance to other points (the square of the distance is returned) """
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def get_sqr_dist(self, other):
        dist = abs(other.x - self.x) + abs(other.y - self.y)
        return dist


class TrackMap:
    """Track map class; does all track map related processing."""

    def __init__(self, points, visualization_frequency=0):
        """Create a new track map object.

        The unit (if any) of F1's coordinate system is unknown to me. Approx.: value / 3,61 = value in meters
        There seems to be one data point per meter of track length.

        :param points: Pandas DataFrame with columns 'X' and 'Y' for point coordinates
        :type points: pandas.DataFrame
        :param visualization_frequency: (optional) specify  after how many calculated points the plot should be updated.
            Set to zero for never (default: never)
        :type visualization_frequency: int
        """

        self.unsorted_points = list()
        self.sorted_points = list()
        self.excluded_points = list()

        self.distances = list()
        self.distances_normalized = list()

        self.track = None

        self._next_point = None

        self._vis_freq = visualization_frequency
        self._vis_counter = 0

        # create a points object for each point
        for index, data in points.iterrows():
            self.unsorted_points.append(Point(data['X'], data['Y']))

        if self._vis_freq:
            plt.ion()
            self._fig = plt.figure()
            self._ax = self._fig.add_subplot(111)
            self._ax.axis('equal')
            self._line2, = self._ax.plot((), (), 'r-')
            self._line1, = self._ax.plot((), (), 'b-')

    def _visualize_sorting_progress(self):
        """Do a visualization of the current progress.
        Updates the plot with the current data.
        """
        if not self._vis_freq:
            return

        self._vis_counter += 1

        if self._vis_counter % self._vis_freq == 0:
            # visualize current state
            xvals_sorted = list()
            yvals_sorted = list()
            for point in self.sorted_points:
                xvals_sorted.append(point.x)
                yvals_sorted.append(point.y)

            xvals_unsorted = list()
            yvals_unsorted = list()
            for point in self.unsorted_points:
                xvals_unsorted.append(point.x)
                yvals_unsorted.append(point.y)

            # update plot
            self._line1.set_data(xvals_sorted, yvals_sorted)  # set plot data
            self._line2.set_data(xvals_unsorted, yvals_unsorted)  # set plot data
            self._ax.relim()  # recompute the data limits
            self._ax.autoscale_view()  # automatic axis scaling
            self._fig.canvas.draw()
            self._fig.canvas.flush_events()

    def _integrate_distance(self):
        """Integrate distance over all points and save distance since start for each point."""
        self.distances.append(0)  # distance is obviously zero at the starting point

        distance_covered = 0  # distance since first point

        for i in range(1, len(self.sorted_points)):
            # calculate the length of the segment between the last and the current point
            segment_length = sqrt(self.sorted_points[i-1].get_sqr_dist(self.sorted_points[i]))
            distance_covered += segment_length
            self.distances.append(distance_covered)

        for dist in self.distances:
            self.distances_normalized.append(dist / self.distances[-1])

    def _sort_points(self):
        """Does the actual sorting of points."""
        # sort points
        # Get the first point as a starting point. Any point could be used as starting point. Later the next closest point is used as next point.
        self._next_point = self.unsorted_points.pop(0)

        while self.unsorted_points:
            self._visualize_sorting_progress()

            # calculate all distances between the next point and all other points
            distances = list()
            for pnt in self.unsorted_points:
                distances.append(self._next_point.get_sqr_dist(pnt))

            # get the next closest point and its index
            min_dst = min(distances)
            min_index = distances.index(min_dst)

            # Check if the closest point is within a reasonable distance. There are some outliers which are very clearly not on track.
            # The limit value was determined experimentally. Usually the distance between to points is approx. 100.
            # (This is the square of the distance. Not the distance itself.)
            # If the _next_point has no other point within a reasonable distance, it is considered an outlier and removed.
            if min_dst > 200:
                self.excluded_points.append(self._next_point)
            else:
                self.sorted_points.append(self._next_point)

            # Get a new _next_point. The new point is the one which was closest to the last one.
            self._next_point = self.unsorted_points.pop(min_index)

    def generate_track(self):
        """Generate a track map from the raw points.

        Sorts all points. Then determines the correct direction and starting point.
        Finally the lap distance is calculated by integrating over all points.
        The distance since start is saved for each point. Additionally, the lap distance is saved normalized to a range of 0 to 1."""

        self._sort_points()
        self._integrate_distance()

        xvals = list()
        yvals = list()
        for point in self.sorted_points:
            xvals.append(point.x)
            yvals.append(point.y)

        self.track = pd.DataFrame({'X': xvals,
                                   'Y': yvals,
                                   'Distance': self.distances,
                                   'Normalized': self.distances_normalized})

    def print_stats(self):
        print("Number of points: {}".format(len(self.sorted_points)))
        print("Excluded points: {}".format(len(self.excluded_points)))


def round_date(ser, freq):
    ser['Date'] = ser['Date'].round(freq)
    return ser


def round_coordinates(ser):
    ser['X'] = round(ser['X'], 3)
    ser['Y'] = round(ser['Y'], 3)
    ser['Z'] = round(ser['Z'], 3)
    return ser


def remove_duplicates(l_ref, l2):
    l_ref_out = list()
    l2_out = list()
    while l_ref:
        itm_ref = l_ref.pop(0)
        itm_2 = l2.pop(0)
        if not itm_ref in l_ref_out:
            l_ref_out.append(itm_ref)
            l2_out.append(itm_2)

    return l_ref_out, l2_out


def get_closest_time_to(frame, t):
    return frame.iloc[abs((frame.index - t)).argsort()[0]]


def reject_outliers(data, *secondary, m=2.):
    d = np.abs(data - np.median(data))
    mdev = np.median(d)
    s = d/mdev if mdev else 0.

    ret_secondary = list()
    for i in range(len(secondary)):
        ret_secondary.append(secondary[i][s < m])

    return data[s < m], *ret_secondary


def _s3_to_start_finish_subprocess(drvs, laps_data, pos, sample_freq, ret_vals):
    end_vals_x = list()
    end_vals_y = list()
    start_vals_x = list()
    start_vals_y = list()

    for drv in drvs:
        print('Driver', drv)
        laps_this_driver = laps_data[laps_data.Driver == drv]
        max_laps = int(laps_this_driver['NumberOfLaps'].max())

        for i in range(1, max_laps):
            print(i)
            time_lap = laps_this_driver.query('NumberOfLaps == @i')['Time'].squeeze()
            sector3time = laps_this_driver.query('NumberOfLaps == @i')['Sector3Time'].squeeze().round(sample_freq)

            search_range_start = time_lap - sector3time - pd.Timedelta('00:00:01.5')
            search_range_end = time_lap + pd.Timedelta('00:00:01.5')  # TODO improvement cut out unnecessary middle part

            # range from shortly before end of sector 2 to shortly after start/finish line
            filtered_pos = pos[drv].query('@search_range_start <= Time <= @search_range_end')

            # round everything to ms precision
            filtered_pos = filtered_pos.apply(round_date, axis=1, freq=sample_freq)

            # interpolate data to 10ms frequency
            # first getz indices and upsample
            ser = filtered_pos['Date']
            idx = pd.date_range(start=ser.iloc[0], end=ser.iloc[-1], freq=sample_freq)

            # create new empty data frame from upsampled indices
            update_df = pd.DataFrame({'Time': None, 'Status': None, 'X': np.NaN, 'Y': np.NaN, 'Z': np.NaN}, index=idx)
            filtered_pos.set_index('Date', inplace=True)

            # update the extended data frame with know data
            update_df.update(filtered_pos)
            # drop unnecessary columns
            update_df.drop(columns=['Time', 'Status'], inplace=True)
            # interpolate missing position data
            update_df = update_df.interpolate().apply(round_coordinates, axis=1)

            # print(update_df)

            time0 = update_df.index[0]

            for dt in range(0, 4000, 10):
                try:
                    timedelta = pd.Timedelta(dt, unit='ms')

                    end_time = time0 + sector3time + timedelta

                    end_v = update_df.loc[end_time]
                    end_vals_x.append(end_v['X'])
                    end_vals_y.append(end_v['Y'])

                    start_vals_x.append(update_df['X'][0])
                    start_vals_y.append(update_df['Y'][0])

                except KeyError:
                    break  # TODO figure out how to get the actual length of the iteration

    ret_dict = {'xs': start_vals_x, 'ys': start_vals_y, 'xe': end_vals_x, 'ye': end_vals_y}
    ret_vals.put(ret_dict)


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def s3_to_start_finish_v1():
    # ###
    drivers = list(tel.keys())

    sample_freq = '10ms'

    q = mp.Queue()

    number_of_processes = 4
    _processes = list()
    for drvs_chunk in chunks(drivers, int(len(drivers)/number_of_processes)+1):
        p = mp.Process(target=_s3_to_start_finish_subprocess, args=(drvs_chunk, laps_data, pos, sample_freq, q))
        _processes.append(p)
        p.start()

    result = {'xs': list(), 'ys': list(), 'xe': list(), 'ye': list()}
    for i in range(number_of_processes):
        from_q = q.get()
        for key in result.keys():
            result[key].extend(from_q[key])

    print('Waiting to finish')
    time.sleep(5)
    print('joining')
    for p in _processes:
        print('+*')
        p.join()
        print('~')

    print('Done')

    end_vals_x = result['xe']
    end_vals_y = result['ye']
    start_vals_x = result['xs']
    start_vals_y = result['ys']

    pickle.dump(end_vals_x, open("var_dumps/end_vals_x_{}".format(sample_freq), "wb"))
    pickle.dump(end_vals_y, open("var_dumps/end_vals_y_{}".format(sample_freq), "wb"))
    pickle.dump(start_vals_x, open("var_dumps/start_vals_x_{}".format(sample_freq), "wb"))
    pickle.dump(start_vals_y, open("var_dumps/start_vals_y_{}".format(sample_freq), "wb"))


if __name__ == '__main__':
    # dump_track_points_to_csv(csv_name)
    track_points = track_points_from_csv(csv_name)
    track_map = TrackMap(points=track_points, visualization_frequency=0)
    track_map.generate_track()

    # session = core.get_session(YEAR, GP, EVENT)
    # pos = api.position(session.api_path)
    # tel = api.car_data(session.api_path)
    # laps_data, stream_data = api.timing_data(session.api_path)
    #
    # for var, fname in zip((session, pos, tel, laps_data, stream_data), ('session', 'pos', 'tel', 'laps_data', 'stream_data')):
    #     with open("var_dumps/" + fname, "wb") as fout:
    #         pickle.dump(var, fout)
    # sys.exit()

    # session, pos, tel, laps_data, stream_data = None, None, None, None, None
    # for var, fname in zip((session, pos, tel, laps_data, stream_data), ('session', 'pos', 'tel', 'laps_data', 'stream_data')):
    #     with open("var_dumps" + fname, "rb") as fin:
    #         var = pickle.load(fin)

    session = pickle.load(open("var_dumps/session", "rb"))
    pos = pickle.load(open("var_dumps/pos", "rb"))
    tel = pickle.load(open("var_dumps/tel", "rb"))
    laps_data = pickle.load(open("var_dumps/laps_data", "rb"))
    # stream_data = pickle.load(open("var_dumps/stream_data", "rb"))

    # end_vals_x = pickle.load(open("var_dumps/end_vals_x_2ms", "rb"))
    # n = pickle.load(open("var_dumps/n_2ms", "rb"))

    # s3_to_start_finish_v1()

    end_vals_x = pickle.load(open("var_dumps/end_vals_x_10ms", "rb"))
    end_vals_y = pickle.load(open("var_dumps/end_vals_y_10ms", "rb"))
    start_vals_x = pickle.load(open("var_dumps/start_vals_x_10ms", "rb"))
    start_vals_y = pickle.load(open("var_dumps/start_vals_y_10ms", "rb"))

    assert len(start_vals_x) == len(end_vals_x)

    end_vals_x = np.array(end_vals_x)
    end_vals_y = np.array(end_vals_y)
    start_vals_x = np.array(start_vals_x)
    start_vals_y = np.array(start_vals_y)

    print("Number of Data Points:", len(end_vals_x))
    # reject outliers based on end values; most probably cuased by incorrect sector times
    end_vals_x, start_vals_x, start_vals_y, end_vals_y = reject_outliers(end_vals_x, start_vals_x, start_vals_y, end_vals_y)

    print("Dividing data into classes")
    min_start_x = min(start_vals_x)
    max_start_x = max(start_vals_x)
    min_end_x = min(end_vals_x)
    max_end_x = max(end_vals_x)
    min_end_y = min(end_vals_y)
    max_end_y = max(end_vals_y)
    n_classes = 150

    step_start_x = (max_start_x - min_start_x) / n_classes
    step_end_x = (max_end_x - min_end_x) / n_classes
    step_end_y = (max_end_y - min_end_y) / n_classes

    classified_start_x = list()
    classified_end_x = list()
    classified_end_y = list()
    classified_n = list()

    end_x_range_0 = min_end_x
    end_y_range_0 = min_end_y
    start_x_range_0 = min_start_x

    for _ in range(n_classes):
        start_x_range_1 = start_x_range_0 + step_start_x
        end_x_range_1 = end_x_range_0 + step_end_x
        end_y_range_1 = end_y_range_0 + step_end_y

        classified_start_x.append((start_x_range_1 + start_x_range_0) / 2)
        classified_end_x.append((end_x_range_1 + end_x_range_0) / 2)
        classified_end_y.append((end_y_range_1 + end_y_range_0) / 2)

        counter = 0
        for i in range(len(end_vals_x)):
            if (start_x_range_0 <= start_vals_x[i] < start_x_range_1) and (end_x_range_0 <= end_vals_x[i] < end_x_range_1):
                counter += 1
        classified_n.append(counter)

        start_x_range_0 += step_start_x
        end_x_range_0 += step_end_x
        end_y_range_0 += step_end_y

    bottom = np.zeros_like(classified_n)

    # generating graphs
    print('Generating plots')
    fig = plt.figure()

    ax1 = fig.add_subplot(2, 2, 1, projection='3d')
    ax1.bar3d(classified_start_x, classified_end_x, bottom, 10, 10, classified_n, shade=True)
    ax1.set_xlabel("Start X")
    ax1.set_ylabel("End X")
    ax1.set_zlabel("N")

    ax2 = fig.add_subplot(2, 2, 2)
    ax2.bar(classified_end_x, classified_n)
    ax2.set_xlabel("End X")
    ax2.set_ylabel("N")

    x_guess = classified_end_x[classified_n.index(max(classified_n))]
    y_guess = classified_end_y[classified_n.index(max(classified_n))]
    ax3 = fig.add_subplot(2, 2, 3)
    ax3.scatter(start_vals_y, start_vals_x, color='r')
    ax3.scatter(end_vals_y, end_vals_x, color='y')
    ax3.plot(track_map.track.Y, track_map.track.X, color='g')
    ax3.axhline(x_guess, min(classified_end_y), max(classified_end_y))
    ax3.axvline(y_guess, min(classified_end_x), max(classified_end_x))
    ax3.set_xlabel("Y")
    ax3.set_ylabel("X")
    ax3.axis('equal')
    ax3.invert_yaxis()

    ax4 = fig.add_subplot(2, 2, 4)
    ax4.bar(classified_end_y, classified_n)
    ax4.set_xlabel("End Y")
    ax4.set_ylabel("N")

    plt.show()

    pass