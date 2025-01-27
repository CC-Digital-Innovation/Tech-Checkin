from dataclasses import dataclass
from datetime import date, datetime, time

from geopy.geocoders import GeoNames
from loguru import logger
from smartsheet import Smartsheet
from smartsheet.models import Cell, Column, Row

symbols_to_ignore = ['(', ')', '-', ' ', '.', '+']
prep_translate_table_dict = {symbol: None for symbol in symbols_to_ignore}
NUMBER_TRANSLATE_TABLE = str.maketrans(prep_translate_table_dict)


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


@dataclass(frozen=True, slots=True)
class TechDetails:
    site_id: str
    tech_name: str
    tech_contact: str
    address: str
    appt_datetime: datetime


class AllTrackerSheet(Sheet):
    def __init__(self, sheet):
        super().__init__(sheet)

    def get_24_hour_checkbox(self, row: Row) -> bool:
        return bool(self.get_cell_by_column_name(row, '24 hour call').value)
    
    def set_24_hour_checkbox(self, row: Row, status: bool):
        self.set_checkbox(row, '24 hour call', status)

    def get_1_hour_checkbox(self, row: Row) -> bool:
        return bool(self.get_cell_by_column_name(row, '1 HR Call').value)

    def set_1_hour_checkbox(self, row: Row, status: bool):
        self.set_checkbox(row, '1 hour call', status)

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

    def get_tech_contact(self, row: Row) -> str:
        # query number and remove symbols. Removes leading '+' if there but will add later
        clean_number = self.get_cell_by_column_name(row, 'Tech Phone #').value.translate(NUMBER_TRANSLATE_TABLE)
        # ensure US country code
        if len(clean_number) == 10:
            number = f'+1{clean_number}'
        elif len(clean_number) == 11:
            number = f'+{clean_number}'
        elif len(clean_number) < 10:
            raise ValueError(f'Number is too short: {clean_number}')
        else:
            raise ValueError(f'Number is too long: {clean_number}')
        return number

    def get_site_id(self, row: Row) -> str:
        return int(self.get_cell_by_column_name(row, 'COMCAST PO').value)

    def get_tech_details(self, row: Row, geolocator: GeoNames | None = None) -> TechDetails:
        return TechDetails(
            self.get_site_id(row),
            self.get_tech_name(row),
            self.get_tech_contact(row),
            self.get_appt_full_address(row),
            self.get_appt_datetime(row, geolocator)
        )


class SmartsheetController:
    def __init__(self, access_token: str = None):
        self.client = Smartsheet(access_token)
        self.client.errors_as_exceptions(True)

    def get_sheet(self, sheet_id) -> AllTrackerSheet:
        return AllTrackerSheet(self.client.Sheets.get_sheet(sheet_id))

    def update_rows(self, sheet):
        if sheet.row_updates:
            return self.client.Sheets.update_rows(sheet.sheet.id, list(sheet.row_updates.values()))
