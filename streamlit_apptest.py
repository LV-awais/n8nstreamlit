import json
import logging
import uuid
import pycountry  # To fetch all countries
import streamlit as st
import requests
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Constants
WEBHOOK_URL = "https://singularly-unique-crappie.ngrok-free.app/webhook/66c8c4ee-d169-4015-8cff-72921f491c97"
BEARER_TOKEN = "thisissomerandomstring"
SERVICE_ACCOUNT_FILE = 'credentials.json'  # Your Google API credentials file

# Google Drive API Scopes
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']

# Generate session ID for uniqueness
def generate_session_id():
    return str(uuid.uuid4())

# Send message to the LLM via the Webhook URL
def send_message_to_llm(session_id, message):
    headers = {"Content-Type": "application/json"}
    payload = {"sessionId": session_id, "chatInput": message}
    response = requests.post(WEBHOOK_URL, json=payload, headers=headers)
    if response.status_code == 200:
        try:
            print(response.json())
            return response.json()
        except ValueError:
            print("⚠️ Response not in JSON format:", response.text)
            return None
    else:
        print(f"❌ Request failed with status {response.status_code}: {response.text}")
        return None

# Authenticate with Google services (Drive API)
def authenticate_google_services():
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    sheets_service = build('sheets', 'v4', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)
    return sheets_service, drive_service

# Modify Google Drive file permissions to make it public
def modify_file_permissions(spreadsheet_id: str, email_address: str = None) -> str:
    try:
        # Set file permissions to 'anyone' with 'reader' access
        permission_body = {
            'type': 'anyone',  # 'anyone' allows anyone with the link to access
            'role': 'reader'   # 'reader' gives view-only access
        }
        drive_service = authenticate_google_services()[1]  # Get drive_service
        # Update permissions for the file
        drive_service.permissions().create(
            fileId=spreadsheet_id,
            body=permission_body,
            fields='id'
        ).execute()

        # Optionally, if an email is provided, grant 'writer' access
        if email_address:
            permission_body = {
                'type': 'user',
                'role': 'writer',
                'emailAddress': email_address
            }
            drive_service.permissions().create(
                fileId=spreadsheet_id,
                body=permission_body,
                fields='id'
            ).execute()

        logging.info(f"Permissions modified for file: ID={spreadsheet_id}")
        return f"Permissions successfully modified!\nID: {spreadsheet_id}\n" \
               f"Permission granted to 'anyone' with 'reader' access." \
               f"{' Additional writer permissions granted to ' + email_address if email_address else ''}"

    except HttpError as error:
        logging.error(f"An error occurred while modifying permissions: {error}")
        return f"Error occurred while modifying file permissions: {error}"

    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        return f"An unexpected error occurred: {str(e)}"

# Create a new Google Sheet
def create_spreadsheet(sheets_service, title="Authorized Distributors"):
    spreadsheet = {
        'properties': {
            'title': title
        }
    }
    request = sheets_service.spreadsheets().create(body=spreadsheet)
    response = request.execute()
    return response['spreadsheetId']

# Add data to the Google Sheet
def add_data_to_sheet(sheets_service, spreadsheet_id, data):
    range_ = 'Sheet1!A1'
    rows = []
    # Split the rows by newline and columns by |
    table_lines = data.split("\n")

    for line in table_lines:
        # Remove leading/trailing whitespace and split by '|'
        row = [cell.strip() for cell in line.split("|")[1:-1]]
        rows.append(row)

    # Create the body for the request to add data
    body = {
        'values': rows
    }

    # Write the values into the sheet
    sheets_service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_,
        valueInputOption="RAW",
        body=body
    ).execute()

    # Add hyperlinks to the URLs in the sheet
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            if cell.startswith("http"):
                # Create the hyperlink formula for the cell
                hyperlink_formula = f'=HYPERLINK("{cell}", "{cell}")'
                sheets_service.spreadsheets().values().update(
                    spreadsheetId=spreadsheet_id,
                    range=f"Sheet1!{chr(65 + j)}{i + 1}",
                    valueInputOption="USER_ENTERED",
                    body={'values': [[hyperlink_formula]]}
                ).execute()

    # Make the first row (headers) bold
    requests = [{
        "updateCells": {
            "range": {
                "sheetId": 0,
                "startRowIndex": 0,
                "endRowIndex": 1,
                "startColumnIndex": 0,
                "endColumnIndex": len(rows[0])
            },
            "rows": [{
                "values": [{
                    "userEnteredFormat": {
                        "textFormat": {"bold": True}
                    }
                }] * len(rows[0])
            }],
            "fields": "userEnteredFormat.textFormat.bold"
        }
    }]
    sheets_service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": requests}
    ).execute()

# Main Streamlit app
def main():
    st.title("Authorized Distributors & Suppliers Lookup")

    # Initialize session state
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "session_id" not in st.session_state:
        st.session_state.session_id = generate_session_id()

    # Fetch list of all countries using pycountry
    countries = sorted([country.name for country in pycountry.countries])
    selected_country = st.selectbox("Select a country", countries)
    brand_name = st.text_input("Enter the name of the brand")

    # Trigger the search with a button
    if st.button("Find Distributors"):
        if not brand_name:
            st.warning("Please enter a brand name first.")
        else:
            # Construct the query
            constructed_prompt = f"search for authorised distributors/suppliers of {brand_name} in {selected_country}"

            # Add to session messages
            st.session_state.messages.append({"role": "user", "content": constructed_prompt})
            with st.chat_message("user"):
                st.write(f"Process Initialised for searching the suppliers of {brand_name}")

            llm_response = send_message_to_llm(st.session_state.session_id, constructed_prompt)
            print(llm_response)
            if llm_response:
                # Fetch the output (distributors table) from the response
                output = llm_response.get("output", "")
                st.write(f"Here's the table of authorized distributors/suppliers:\n\n{output}")
                # Directly use 'output' as a string
                if output:
                    # Authenticate with Google services (Drive API)
                    sheets_service, drive_service = authenticate_google_services()

                    # Create a new spreadsheet
                    spreadsheet_id = create_spreadsheet(sheets_service, title="Authorized Distributors")

                    # Add the output data to the sheet
                    add_data_to_sheet(sheets_service, spreadsheet_id, output)

                    # Modify permissions for the newly created Google Sheet
                    modify_file_permissions(spreadsheet_id)

                    st.write(f"Data has been added to the Google Sheet.")
                    google_sheets_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
                    st.markdown(f'<a href="{google_sheets_url}" target="_blank"><button>Open Google Sheet</button></a>',
                                unsafe_allow_html=True)
                else:
                    st.error("❌ No distributor data found.")
            else:
                st.error("❌ Failed to get response from the LLM.")

            st.session_state.messages.append({"role": "assistant", "content": llm_response})

    # # Display previous chat messages
    # for message in st.session_state.messages:
    #     if message not in st.session_state.get("displayed", []):
    #         with st.chat_message(message["role"]):
    #             st.write(message["content"])
    #         st.session_state.setdefault("displayed", []).append(message)

# Run the Streamlit app
if __name__ == "__main__":
    main()
