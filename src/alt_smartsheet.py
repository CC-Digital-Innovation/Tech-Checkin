from dataclasses import dataclass
from datetime import date, datetime, time
from functools import cache

import phonenumbers
from geopy.exc import GeocoderTimedOut
from geopy.geocoders import GeoNames
from loguru import logger
from phonenumbers import PhoneNumber
from smartsheet import Smartsheet
from smartsheet.models import (Cell, Comment, Discussion, Report, ReportRow,
                               Row, Sheet)


@dataclass(frozen=True, slots=True)
class TechDetails:
    site_id: str
    tech_name: str
    tech_contact: PhoneNumber
    address: str
    appt_datetime: datetime
    work_market_num: str
    work_order_num: str


class AltSheet:
    def __init__(self, sheet: Sheet):
        self.sheet = sheet
        self.rows = sheet.rows
        self.columns = sheet.columns
        # The API identifies columns by Id, but it's more convenient to refer to column names
        self._column_map = {column.title: column.id for column in sheet.columns}
        # Keeps a running track of updates using row ID as keys and the row object as values
        # When running update_rows, use list(row_updates.values())
        self.row_updates = {}

    # Helper function to find cell in a row
    def get_cell_by_column_name(self, row, column_name) -> Cell:
        column_id = self._column_map[column_name]
        return row.get_column(column_id)

    def set_checkbox(self, row: Row, column_name: str, status: bool):
        # build new cell
        new_cell = Cell()
        new_cell.column_id = self._column_map[column_name]
        new_cell.value = status

        try:
            # get existing row to update and append cells
            self.row_updates[row.id].cells.append(new_cell)
        except KeyError:
            # build row to update
            new_row = Row()
            new_row.id = row.id
            new_row.cells.append(new_cell)
            self.row_updates[new_row.id] = new_row


@cache
def _cached_geocode(geolocator: GeoNames, query, country='US'):
    return geolocator.geocode(query, country=country)

@cache
def _cached_reverse_timezone(geolocator: GeoNames, point):
    return geolocator.reverse_timezone(point)


class AllTrackerSheet(AltSheet):
    def __init__(self, sheet: Sheet, geolocator: GeoNames | None = None) -> 'AllTrackerSheet':
        super().__init__(sheet)
        self.geolocator = geolocator

    def set_24_hour_checkbox(self, row: Row, status: bool):
        self.set_checkbox(row, '24 HR Pre-call', status)

    def set_1_hour_checkbox(self, row: Row, status: bool):
        self.set_checkbox(row, '1 HR Pre-call', status)

    def get_24_hour_checkbox(self, row: Row) -> bool:
        return bool(self.get_cell_by_column_name(row, '24 HR Pre-call').value)

    def get_1_hour_checkbox(self, row: Row) -> bool:
        return bool(self.get_cell_by_column_name(row, '1 HR Pre-call').value)

    def get_postal_code(self, row: Row) -> str:
        value = self.get_cell_by_column_name(row, 'Zip Code').value
        try:
            # cast to int since some values can come in as float
            # cast to str since there can be leading zeros
            postal_code = str(int(value))
        except ValueError:
            # validate input which should contain a full 9 digit zip code with a hyphen
            if len(value) != 10:
                raise ValueError(f'Unrecognized number of digits for zip {value}.')
            split_postal = value.split('-')
            if len(split_postal) != 2 or len(split_postal[0]) != 5 or len(split_postal[1]) != 4:
                raise ValueError(f'Unrecognized format for zip {value}.')
            return value
        # fill in missing leading zeros
        if len(postal_code) < 5:
            postal_code = ('0' * (5 - len(postal_code))) + postal_code
        return postal_code

    def get_appt_date(self, row: Row) -> date:
        return date.fromisoformat(self.get_cell_by_column_name(row, 'Secured Date').value)

    def get_appt_datetime(self, row: Row) -> datetime:
        appt_date = self.get_appt_date(row)
        appt_time = int(self.get_cell_by_column_name(row, 'Secured Time').value)
        hour = appt_time // 100
        minute = appt_time % 100
        appt_datetime = datetime.combine(appt_date, time(hour, minute))
        if self.geolocator is not None:
            # get timezone from address
            postal_code = self.get_postal_code(row)
            try:
                location = _cached_geocode(self.geolocator, postal_code)
                if location is None:
                    city = self.get_cell_by_column_name(row, 'City').value
                    state = self.get_cell_by_column_name(row, 'State').value
                    location =  _cached_geocode(self.geolocator, f'{city}, {state}')
                    if location is None:
                        msg = f'Error geocoding from zip ({postal_code}) and city, state ({city}, {state}) on row #{row.row_number}.'
                        logger.warning(msg)
                        raise ValueError(msg)
            except GeocoderTimedOut as e:
                logger.exception(e)
                raise ValueError(f'Error from geocode: {e}') from e
            reversed_timezone = _cached_reverse_timezone(self.geolocator, (location.latitude, location.longitude))
            appt_datetime = reversed_timezone.pytz_timezone.localize(appt_datetime)
        return appt_datetime

    def get_appt_full_address(self, row: Row) -> str:
        address = self.get_cell_by_column_name(row, 'Address').value
        if address is None:
            address = ''
        address = address.strip().replace(',', '').replace('\n', ' ')
        city = self.get_cell_by_column_name(row, 'City').value
        if city is None:
            city = ''
        city = city.strip()
        state = self.get_cell_by_column_name(row, 'State').value
        if state is None:
            state = ''
        state = state.strip()
        postal_code = self.get_postal_code(row)
        return ', '.join((address, city, state, postal_code))

    def get_tech_name(self, row: Row) -> str:
        return str(self.get_cell_by_column_name(row, 'Tech Name (First and Last)').value)

    def get_tech_contact(self, row: Row, region: str = 'US') -> str:
        query = self.get_cell_by_column_name(row, 'Tech Phone #').value
        if isinstance(query, float):
            query = int(query)  # cast to int to remove trailing zero
        num = str(query)  # cast to str as query can be other types
        try:
            parsed_num = phonenumbers.parse(num, region)
        except phonenumbers.NumberParseException as e:
            msg = f'Error parsing number on row #{row.row_number}: {e}'
            logger.warning(msg)
            raise ValueError(msg) from e
        if not phonenumbers.is_valid_number(parsed_num):
            msg = f'Error parsing number on row #{row.row_number}: Number {parsed_num.national_number} is not valid for region {region}.'
            logger.warning(msg)
            raise ValueError(msg)
        return parsed_num

    def get_site_id(self, row: Row) -> str:
        return str(self.get_cell_by_column_name(row, 'SITE ID').value)

    def get_work_order_num(self, row: Row) -> str:
        try:
            return str(int(self.get_cell_by_column_name(row, 'COMCAST PO').value))  # possible float, cast to int first to remove precision
        except ValueError:
            return str(self.get_cell_by_column_name(row, 'COMCAST PO').value)
        except TypeError:
            return ''  # parsed None

    def get_work_market_num_id(self, row: Row) -> str:
        # cast to int first to remove trailing zero
        raw_result = self.get_cell_by_column_name(row, 'WORK MARKET #').value
        try:
            result = int(raw_result)
        except ValueError:
            try:
                split = raw_result.split('/')
                result = int(split[-1])
            except Exception as e:
                raise ValueError(f"Work market number ran into an uncaught exception case: {e}") from e
        except TypeError:
            logger.warning(f'Work market number is None or cannot be parsed at row #{row.row_number}')
            return ''
        return str(result)

    def get_tech_details(self, row: Row, datetime_: datetime | None = None) -> TechDetails:
        return TechDetails(
            site_id=self.get_site_id(row),
            tech_name=self.get_tech_name(row),
            tech_contact=self.get_tech_contact(row),
            address=self.get_appt_full_address(row),
            appt_datetime=self.get_appt_datetime(row) if datetime_ is None else datetime_,
            work_market_num=self.get_work_market_num_id(row),
            work_order_num=self.get_work_order_num(row)
        )


class AltReport(AltSheet):
    def __init__(self, report: Report):
        self.discussions = report.discussions
        self.source_sheets = {src_sheet.id: AllTrackerSheet(src_sheet) for src_sheet in report.source_sheets}
        super().__init__(report)

    # Helper function to find cell in a row
    def get_cell_by_column_name(self, row: ReportRow, column_name: str) -> Cell:
        sheet = self.source_sheets[row.sheet_id]
        return sheet.get_cell_by_column_name(row, column_name)

    def set_checkbox(self, row: ReportRow, column_name: str, status: bool):
        sheet = self.source_sheets[row.sheet_id]
        sheet.set_checkbox(row, column_name, status)


class AllTrackerReport(AltReport, AllTrackerSheet):
    def __init__(self, report: Report, geolocator: GeoNames | None = None):
        super().__init__(report)
        self.geolocator = geolocator

    def set_24_hour_checkbox(self, row: ReportRow, status: bool):
        sheet = self.source_sheets[row.sheet_id]
        sheet.set_checkbox(row, '24 HR Pre-call', status)

    def set_1_hour_checkbox(self, row: ReportRow, status: bool):
        sheet = self.source_sheets[row.sheet_id]
        sheet.set_checkbox(row, '1 HR Pre-call', status)


class SmartsheetController:
    def __init__(self, access_token: str = None):
        self.client = Smartsheet(access_token)
        self.client.errors_as_exceptions(True)

    def get_sheet(self, sheet_id: str, geolocator: GeoNames | None = None) -> AllTrackerSheet:
        return AllTrackerSheet(self.client.Sheets.get_sheet(sheet_id), geolocator)

    def get_report(self, report_id: str, geolocator: GeoNames | None = None) -> AllTrackerReport:
        return AllTrackerReport(self.client.Reports.get_report(report_id, include=['sourceSheets']), geolocator)

    def update_rows(self, sheet: AllTrackerSheet | AllTrackerReport):
        try:
            # update report
            for s in sheet.source_sheets.values():
                self.update_rows(s)
        except AttributeError:
            # update sheet
            if sheet.row_updates:
                return self.client.Sheets.update_rows(sheet.sheet.id, list(sheet.row_updates.values()))

    def get_discussions(self, sheet_id):
        response = self.client.Discussions.get_all_discussions(sheet_id, include_all=True)
        return response.data
    
    def create_discussion_on_row(self, sheet_id, row_id, comment):
        discuss = Discussion({'comment': Comment({'text' : comment})})
        self.client.Discussions.create_discussion_on_row(sheet_id, row_id, discuss)

    def create_comment(self, sheet_id, discussion_id, comment):
        comm = Comment({'text': comment})
        self.client.Discussions.add_comment_to_discussion(sheet_id, discussion_id, comm)
