# Original https://www.apogeeinstruments.com/apogee-usb-sensors-and-linux/
# chatGPT updated to python3, adding get logged data and CLI

from time import sleep

import pandas as pd

import struct
import argparse
import csv
from datetime import datetime, timedelta
from serial import Serial, SerialException


GET_VOLT = b'\x55!'

READ_CALIBRATION = b'\x83!'

SET_CALIBRATION = b'\x84%s%s!'

READ_SERIAL_NUM = b'\x87!'

GET_LOGGING_COUNT = b'\xf3!'

GET_LOGGED_ENTRY = b'\xf2%s!'

ERASE_LOGGED_DATA = b'\xf4!'


def try_convert_date(val):
    try:
        return pd.to_datetime(val)
    except ValueError:
        return pd.NaT  # Return 'not a time' for invalid dates


class Quantum(object):

    def __init__(self, port):
        self.quantum = None
        self.offset = 0.0
        self.multiplier = 0.0
        self.port = port
        self.connect_to_device()

    def connect_to_device(self):
        """This function creates a Serial connection with the defined comport

        and attempts to read the calibration values"""

        try:
            self.quantum = Serial(self.port, 115200, timeout=0.5)

            self.quantum.write(READ_CALIBRATION)

            multiplier = self.quantum.read(5)[1:]

            offset = self.quantum.read(4)

            self.multiplier = struct.unpack('<f', multiplier)[0]

            self.offset = struct.unpack('<f', offset)[0]

        except SerialException:
            print("Can't locate device")
            self.quantum = None

    def get_micromoles(self):
        """This function converts the voltage to micromoles"""

        voltage = self.read_voltage()

        if voltage == 9999:

            # you could raise some sort of Exception here if you wanted to

            return

        # this next line converts volts to micromoles

        micromoles = (voltage - self.offset) * self.multiplier * 1000

        if micromoles < 0:

            micromoles = 0

        return micromoles

    def read_voltage(self):
        """This function averages 5 readings over 1 second and returns

        the result."""

        if self.quantum is None:

            try:

                self.connect_to_device()

            except IOError:

                # you can raise some sort of exception here if you need to

                return

        # store the responses to average

        response_list = []

        # change to average more or less samples over the given time period

        number_to_average = 5

        # change to shorten or extend the time duration for each measurement

        # be sure to leave as floating point to avoid truncation

        number_of_seconds = 1.0

        for i in range(number_to_average):

            try:

                self.quantum.write(GET_VOLT)

                response = self.quantum.read(5)[1:]

            except IOError as data:

                print(data)

                # dummy value to know something went wrong. could raise an

                # exception here alternatively

                return 9999

            else:

                if not response:

                    continue

                # if the response is not 4 bytes long, this line will raise

                # an exception

                voltage = struct.unpack('<f', response)[0]
                response_list.append(voltage)

                sleep(number_of_seconds / number_to_average)

        if response_list:

            return sum(response_list) / len(response_list)

        return 0.0

    def erase_logged_data(self):
        try:
            self.quantum.write(ERASE_LOGGED_DATA)
        except IOError as data:
            print(data)
            return False
        return True

    def get_logging_count(self):
        try:
            self.quantum.write(GET_LOGGING_COUNT)
            response = self.quantum.read(5)[1:]
            if response:
                count = struct.unpack('<I', response)[0]
                return count
            else:
                return 0
        except IOError as data:
            print(data)
            return None

    def get_all_logged_entries(self, current_datetime):
        count = self.get_logging_count()
        if count is not None:
            with open('logged_entries.csv', 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['timestamp', 'entry'])

                # Calculate earliest timestamp
                earliest_datetime = current_datetime - timedelta(minutes=count)

                for i in range(count):
                    try:
                        # Convert the index to bytes and pad it to 4 bytes
                        index_bytes = struct.pack('<I', i)
                        self.quantum.write(GET_LOGGED_ENTRY % index_bytes)
                        response = self.quantum.read(5)[1:]
                        if response:
                            entry = struct.unpack('<f', response)[0]
                            timestamp = earliest_datetime + \
                                timedelta(minutes=i)
                            writer.writerow([timestamp, entry])
                        # Output progress information
                        print(f'Progress: {i+1}/{count} entries read.')
                    except IOError as data:
                        print(data)

    def calculate_kwh(self, csv_file, min_val, max_val):
        # specify column names in names parameter
        data = pd.read_csv(csv_file, names=['timestamp', 'entry'])

        # convert 'timestamp' column to datetime and handle errors
        data['timestamp'] = data['timestamp'].apply(try_convert_date)

        # remove rows with invalid dates
        data = data.dropna(subset=['timestamp'])

        # Convert 'entry' to numeric, force non-numeric values to NaN
        data['entry'] = pd.to_numeric(data['entry'], errors='coerce')

        # filter data
        data = data[(data['entry'] >= min_val) & (data['entry'] <= max_val)]

        # calculate sum of 'entry' for each day
        daily_sum = data.resample('D', on='timestamp').sum()

        # convert daily sum to kwh
        daily_kwh = daily_sum['entry'] * 0.001 * (1/60)

        print(daily_kwh)


def calculate_solar_output(panel_count, panel_width, panel_height, panel_wattage, panel_efficiency, daily_kwh):
    # Calculate panel area in square meters
    panel_area = (panel_width / 1000) * (panel_height / 1000) * panel_count

    # Calculate the total kWh produced by the solar panels for each day
    total_kwh = daily_kwh * panel_area * panel_efficiency * panel_wattage
    print(total_kwh)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Quantum device command line interface.')
    parser.add_argument(
        '--port',
        type=str,
        default='/dev/serial/by-id/usb-Apogee_Instruments__Inc._SQ-420_2A4D984631001C00-if00',
        help='The COM port to connect to')
    parser.add_argument(
        '--read_voltage',
        action='store_true',
        help='Read the voltage from the device')
    parser.add_argument(
        '--get_all_logged_entries',
        type=str,
        help='Get all logged entries from the device. Pass the current datetime in format "YYYY-MM-DD HH:MM:SS"')
    parser.add_argument(
        '--erase_logged_data',
        action='store_true',
        help='Erase all logged entries on the device')
    parser.add_argument(
        '--get_micromoles',
        action='store_true',
        help='Get the micromoles from the device')
    parser.add_argument(
        '--calculate_kwh',
        type=str,
        help='Calculate the kWh from a logged entries CSV file')
    parser.add_argument(
        '--min_val',
        type=int,
        default=0,
        help='Minimum value to consider in the kWh calculation')
    parser.add_argument(
        '--max_val',
        type=int,
        default=2000,
        help='Maximum value to consider in the kWh calculation')
    parser.add_argument(
        '--calculate_solar_output',
        nargs=6,
        metavar=('PANEL_COUNT', 'PANEL_WIDTH', 'PANEL_HEIGHT',
                 'PANEL_WATTAGE', 'PANEL_EFFICIENCY', 'DAILY_KWH'),
        help='Calculate the total kWh produced by the solar panels for each day using the daily kWh values'
    )

    args = parser.parse_args()

    q = Quantum(args.port)

    if args.read_voltage:
        print(q.read_voltage())

    if args.get_all_logged_entries:
        current_datetime = datetime.strptime(
            args.get_all_logged_entries, "%Y-%m-%d %H:%M:%S")
        q.get_all_logged_entries(current_datetime)

    if args.erase_logged_data:
        success = q.erase_logged_data()
        if success:
            print("Successfully erased logged data.")
        else:
            print("Failed to erase logged data.")

    if args.get_micromoles:
        print(q.get_micromoles())

    if args.calculate_kwh:
        kwh_per_day = q.calculate_kwh(
            args.calculate_kwh, args.min_val, args.max_val)
        print(kwh_per_day)

    if args.calculate_solar_output:
        panel_count, panel_width, panel_height, panel_wattage, panel_efficiency, daily_kwh = args.calculate_solar_output
        calculate_solar_output(
            int(panel_count),
            int(panel_width),
            int(panel_height),
            int(panel_wattage),
            float(panel_efficiency),
            float(daily_kwh)
        )
