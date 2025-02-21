from dataclasses import dataclass
from datetime import date, datetime, time

import phonenumbers
from geopy.geocoders import GeoNames
from loguru import logger
from phonenumbers import PhoneNumber
from smartsheet import Smartsheet
from smartsheet.models import (Cell, Column, Comment, Discussion, Report,
                               ReportRow, Row)


@dataclass(frozen=True, slots=True)
class TechDetails:
    site_id: str
    tech_name: str
    tech_contact: PhoneNumber
    address: str
    appt_datetime: datetime
    work_market_num: str


class AllTrackerMixin:
    def get_cell_by_column_name(self):
        raise NotImplementedError('required function for mixin.')

    def get_24_hour_checkbox(self, row: Row) -> bool:
        return bool(self.get_cell_by_column_name(row, '24 HR Pre-call').value)

    def get_1_hour_checkbox(self, row: Row) -> bool:
        return bool(self.get_cell_by_column_name(row, '1 HR Pre-call').value)

    def get_postal_code(self, row: Row) -> str:
        # cast to int since some values can come in as float
        # cast to str since there can be leading zeros
        postal_code = str(int(self.get_cell_by_column_name(row, 'Zip Code').value))
        # fill in missing leading zeros
        if len(postal_code) < 5:
            postal_code = ('0' * (5 - len(postal_code))) + postal_code
        return postal_code

    def get_appt_date(self, row: Row) -> date:
        return date.fromisoformat(self.get_cell_by_column_name(row, 'Secured Date').value)

    def get_appt_datetime(self, row: Row, geolocator: GeoNames | None = None) -> time:
        appt_date = self.get_appt_date(row)
        appt_time = int(self.get_cell_by_column_name(row, 'Secured Time').value)
        hour = appt_time // 100
        minute = appt_time % 100
        appt_datetime = datetime.combine(appt_date, time(hour, minute))
        if geolocator:
            # get timezone from address
            postal_code = self.get_postal_code(row)
            location = geolocator.geocode(postal_code, country='US')
            reversed_timezone = geolocator.reverse_timezone((location.latitude, location.longitude))
            appt_datetime = appt_datetime.replace(tzinfo=reversed_timezone.pytz_timezone)
        return appt_datetime

    def get_appt_full_address(self, row: Row) -> str:
        return ', '.join((self.get_cell_by_column_name(row, 'Address').value,
                          self.get_cell_by_column_name(row, 'City').value,
                          self.get_cell_by_column_name(row, 'State').value,
                          self.get_postal_code(row)))

    def get_tech_name(self, row: Row) -> str:
        return self.get_cell_by_column_name(row, 'Tech Name(First and Last)').value

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
        return self.get_cell_by_column_name(row, 'SITE ID').value
    
    def get_work_market_num_id(self, row: Row) -> str:
        # cast to int first to remove trailing zero
        return str(int(self.get_cell_by_column_name(row, 'WORK MARKET #').value))

    def get_tech_details(self, row: Row, geolocator: GeoNames | None = None) -> TechDetails:
        return TechDetails(
            site_id=self.get_site_id(row),
            tech_name=self.get_tech_name(row),
            tech_contact=self.get_tech_contact(row),
            address=self.get_appt_full_address(row),
            appt_datetime=self.get_appt_datetime(row, geolocator),
            work_market_num=self.get_work_market_num_id(row)
        )


class Sheet:
    def __init__(self, sheet):
        self.sheet = sheet
        # The API identifies columns by Id, but it's more convenient to refer to column names
        self._column_map = {column.title: column.id for column in sheet.columns}
        # Keeps a running track of updates using row ID as keys and the row object as values
        # When running update_rows, use list(row_updates.values())
        self.row_updates = {}

    # Helper function to find cell in a row
    def get_cell_by_column_name(self, row, column_name) -> Cell:
        column_id = self._column_map[column_name]
        return row.get_column(column_id)
    
    def get_rows(self) -> list[Row]:
        return self.sheet.rows
    
    def get_columns(self) -> list[Column]:
        return self.sheet.columns

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


class AllTrackerSheet(Sheet, AllTrackerMixin):
    def set_24_hour_checkbox(self, row: Row, status: bool):
        self.set_checkbox(row, '24 HR Pre-call', status)

    def set_1_hour_checkbox(self, row: Row, status: bool):
        self.set_checkbox(row, '1 HR Pre-call', status)


class Report(Sheet):
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


class AllTrackerReport(Report, AllTrackerMixin):
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

    def get_sheet(self, sheet_id) -> AllTrackerSheet:
        return AllTrackerSheet(self.client.Sheets.get_sheet(sheet_id))

    def get_report(self, report_id) -> AllTrackerReport:
        return AllTrackerReport(self.client.Reports.get_report(report_id, include=['sourceSheets']))

    def update_rows(self, sheet):
        if sheet.row_updates:
            return self.client.Sheets.update_rows(sheet.sheet.id, list(sheet.row_updates.values()))

    def update_report_rows(self, report: Report):
        for sheet in report.source_sheets.values():
            self.update_rows(sheet)

    def get_discussions(self, sheet_id):
        response = self.client.Discussions.get_all_discussions(sheet_id, include_all=True)
        return response.data
    
    def create_discussion_on_row(self, sheet_id, row_id, comment):
        discuss = Discussion({'comment': Comment({'text' : comment})})
        self.client.Discussions.create_discussion_on_row(sheet_id, row_id, discuss)

    def create_comment(self, sheet_id, discussion_id, comment):
        comm = Comment({'text': comment})
        self.client.Discussions.add_comment_to_discussion(sheet_id, discussion_id, comm)
