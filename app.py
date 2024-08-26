from flask import Flask, request, jsonify
import pandas as pd
import json
from flask_cors import CORS
from datetime import datetime, timedelta
from rate_quote import RateQuoteAPI, AuptixRateQuoteAPI  # Import the classes
import requests

# Flask app initialization
app = Flask(__name__)
CORS(app)

def load_config():
    with open('config.json', 'r') as file:
        return json.load(file)

def excel_date_to_string(excel_date):
    base_date = datetime(1899, 12, 30)  # Excel's "epoch" date
    delta = timedelta(days=int(excel_date))
    return (base_date + delta).strftime('%Y-%m-%d')

def calculate_freight_class(weight, length, width, height):
    # Calculate volume in cubic feet
    volume = (length * width * height) / 1728  # Convert cubic inches to cubic feet
    density = weight / volume

    # Determine freight class based on density
    if density >= 50:
        return '50'
    elif density >= 35:
        return '55'
    elif density >= 30:
        return '60'
    elif density >= 22.5:
        return '65'
    elif density >= 15:
        return '70'
    elif density >= 13.5:
        return '77.5'
    elif density >= 12:
        return '85'
    elif density >= 10.5:
        return '92.5'
    elif density >= 9:
        return '100'
    elif density >= 8:
        return '110'
    elif density >= 7:
        return '125'
    elif density >= 6:
        return '150'
    elif density >= 5:
        return '175'
    elif density >= 4:
        return '200'
    elif density >= 3:
        return '250'
    elif density >= 2:
        return '300'
    elif density >= 1:
        return '400'
    else:
        return '500'

def map_accessorials(accessorials):
    mapping = {
        'Residential Delivery': 'Delivery',
        'Inside Delivery': 'Delivery',
        'Limited Access or Constr Site Dlvry': 'Delivery',
        'Construction-Utility-Mine or Rmt Del': 'Delivery',
        'Lift Gate Delivery': 'Delivery',
        'Appointment Fee': 'Delivery',
        'Lift Gate Pickup': 'Pickup',
        'Limited Access or Constr Site Pickup': 'Pickup',
        'Construction-Utility-Mine or Rmt Pickup': 'Pickup',
        'Inside Pickup': 'Pickup',
        'Overlength 8 ft but less than 12 ft': 'Delivery',
        'Overlength 12 ft but less than 20 ft': 'Delivery',
        'Overlength 20 ft or greater': 'Delivery',
        'Compliance Services Fee': 'Delivery'
    }
    return [{'accId': acc_id.strip(), 'accName': mapping.get(acc_id.strip(), 'O')} for acc_id in accessorials]
def get_warehouse_address(location):
    addresses = {
        "LA": {
            "customerNumber": "21818977",
            "customerName": "Linktrans",
            "streetAddress": "14650 Meyer Canyon Dr, DOCK 1203",
            "city": "Fontana",
            "state": "CA",
            "zip": "92336"
        },
        "NJ": {
            "customerNumber": "21818978",
            "customerName": "Linktrans",
            "streetAddress": "50 Jiffy Rd",
            "city": "Somerset",
            "state": "NJ",
            "zip": "08873"
        },
        "SVG": {
            "customerNumber": "21818979",
            "customerName": "Linktrans",
            "streetAddress": "139 Prosperity Dr.",
            "city": "Garden City",
            "state": "GA",
            "zip": "31408"
        }
    }
    return addresses.get(location, {})
def process_daylight_quote(so_data, items, mapped_accessorials, daylight_api):
    pickup_date_str = excel_date_to_string(so_data['pick_up_date'])
    warehouse_address = get_warehouse_address(so_data['warehouseLocation'])
    daylight_payload = {
        "dyltRateQuoteReq": {
            "accountNumber": "21818977",
            "userName": "LINKTRANS",
            "password": "daylight",
            "billTerms": "PP",
            "serviceType": "LTL",
            "pickupDate": pickup_date_str,
            "shipperInfo": {
                "customerNumber": warehouse_address.get("customerNumber"),
                "customerName": warehouse_address.get("customerName"),
                "customerAddress": {
                    "streetAddress": warehouse_address.get("streetAddress"),
                    "aptAddress": "",
                    "city": warehouse_address.get("city"),
                    "state": warehouse_address.get("state"),
                    "zip": warehouse_address.get("zip")
                }
            },
            "consigneeInfo": {
                "customerNumber": "",
                "customerName": "",
                "customerAddress": {
                    "streetAddress": so_data.get('street Address', ''),
                    "aptAddress": "",
                    "city": so_data.get('city', ''),
                    "state": so_data.get('state', ''),
                    "zip": str(int(float(so_data.get('zip', ''))))
                }
            },
            "items": {
                "item": items
            },
            "accessorials": {
                "accessorial": mapped_accessorials
            }
        }
    }
    try:
        print(f"Sending Daylight request: {json.dumps(daylight_payload, indent=2)}")
        daylight_response = daylight_api.get_rate_quote(daylight_payload)
        print(f"Received Daylight response: {daylight_response}")
        if isinstance(daylight_response, str):
            daylight_response = json.loads(daylight_response)
        net_charge, freight_class = parse_daylight_response(daylight_response)
        if isinstance(freight_class, str):
            freight_class = freight_class.replace('.', '_')
        return net_charge, f"CLASS_{freight_class}"
    except Exception as e:
        print(f"Error occurred while processing Daylight API: {e}")
        return 'N/A', 'N/A'

def parse_daylight_response(response):
    try:
        if 'dyltRateQuoteResp' in response and response['dyltRateQuoteResp'].get('success') == 'YES':
            net_charge = response['dyltRateQuoteResp']['totalCharges']['netCharge']
            freight_class = response['dyltRateQuoteResp']['itemCharges']['itemCharge'][0]['actualClass']
        else:
            error_message = response['dyltRateQuoteResp'].get('errorInformation', {}).get('errorMessage', 'Unknown error')
            raise ValueError(f"Daylight API error: {error_message}")
        return net_charge, freight_class
    except Exception as e:
        print(f"Error parsing Daylight response: {e}")
        return 'N/A', 'N/A'

def parse_auptix_response(response):
    try:
        rates = {
            'STANDARD_INFLEXIBLE': 'pending',
            'FLOCK_DIRECT_INFLEXIBLE': 'pending'
        }

        for option in response['fulfillmentOptions']:
            if option['serviceLevel'] == 'STANDARD' and option['pickupFlexibility'] == 'INFLEXIBLE':
                rates['STANDARD_INFLEXIBLE'] = option['totalRateUsd']
            elif option['serviceLevel'] == 'FLOCK_DIRECT' and option['pickupFlexibility'] == 'INFLEXIBLE':
                rates['FLOCK_DIRECT_INFLEXIBLE'] = option['totalRateUsd']

        freight_class = response['shipment']['shipmentItems'][0]['freightClass']
        return rates, freight_class
    except Exception as e:
        print(f"Error parsing Auptix response: {e}")
        return {'STANDARD_INFLEXIBLE': 'pending', 'FLOCK_DIRECT_INFLEXIBLE': 'pending'}, 'N/A'

def process_auptix_quote(so_data, items, auptix_api):
    pickup_date_str = excel_date_to_string(so_data['pick_up_date'])
    warehouse_address = get_warehouse_address(so_data['warehouseLocation'])
    # Create a list of shipment items by iterating through all items under the same SO
    shipment_items = []
    for item in items:
        dimensions = item.get('dimensions', '0*0*0')
        length, width, height = map(int, dimensions.split('*'))
        weight = int(item.get('weight', 0))
        freight_class = calculate_freight_class(weight, length, width, height)

        shipment_items.append({
            "quantity": str(item.get('pallets', 1)),
            "packagingType": "PALLET",
            "dimensions": {
                "lengthIn": length,
                "widthIn": width,
                "heightIn": height
            },
            "stackable": False,
            "turnable": True,
            "totalWeightLbs": weight,
            "freightClass": f"CLASS_{freight_class.replace('.', '_')}",
            "description": "General Merchandise"
        })

    auptix_payload = {
        "shipment": {
            "pickupDate": pickup_date_str,
            "pickUpStopDetails": {
                "postalCode": warehouse_address.get("zip"),
                "locationType": "BUSINESS_DOCK",
                "schedulingService": {
                    "type": so_data.get('shipment_ServiceType', 'WINDOW'),
                    "startTime": "09:00",
                    "endTime": "16:00"
                }
            },
            "deliveryStopDetails": {
                "postalCode": str(int(float(so_data.get('zip', '')))),
                "locationType": so_data.get('locationType', 'BUSINESS_NO_DOCK'),
                "hasPalletJackAndForklift": True,
                "schedulingService": {
                    "type": so_data.get('delivery_ServiceType', 'CALL_FOR_APPOINTMENT'),
                    "date": pickup_date_str,
                    "startTime": "09:00",
                    "endTime": "16:00"
                }
            },
            "shipmentItems": shipment_items,  # Use the combined shipment items here
            "additionalServices": {
                "reeferProhibited": True
            }
        }
    }
    try:
        print(f"Sending Auptix request: {json.dumps(auptix_payload, indent=2)}")
        auptix_response = auptix_api.get_rate_quote(auptix_payload)
        print(f"Received Auptix response: {auptix_response}")
        if isinstance(auptix_response, str):
            auptix_response = json.loads(auptix_response)
        rates, freight_class = parse_auptix_response(auptix_response)
        return rates, freight_class
    except requests.exceptions.HTTPError as http_err:
        error_message = f"HTTP error occurred: {http_err.response.text}"  # Capture the full error response
        print(f"Error occurred while processing Auptix API: {error_message}")
        raise ValueError(error_message)  # Raise an error with the detailed message
    except Exception as e:
        print(f"Error occurred while processing Auptix API: {e}")
        return {'STANDARD_INFLEXIBLE': 'N/A', 'FLOCK_DIRECT_INFLEXIBLE': 'N/A'}, 'N/A'

def process_quote(so_grouped_data):
    results = []
    config = load_config()
    daylight_api = RateQuoteAPI(config['daylight'])
    auptix_api = AuptixRateQuoteAPI(config['auptix'])

    for so, so_data in so_grouped_data.items():
        mapped_accessorials = map_accessorials(so_data['Accessorials'].split(','))

        if not so_data['items']:
            print(f"Warning: No items found for SO '{so}'")
            continue

        try:
            daylight_net_charge, daylight_class = process_daylight_quote(so_data, so_data['items'], mapped_accessorials, daylight_api)
        except Exception as e:
            print(f"Error occurred while processing Daylight API: {e}")
            daylight_net_charge, daylight_class = 'N/A', 'N/A'

        try:
            rates, freight_class = process_auptix_quote(
                so_data,
                so_data['items'],  # Pass all items to Auptix
                auptix_api=auptix_api
            )
        except Exception as e:
            print(f"Error occurred while processing Auptix API: {e}")
            rates, freight_class = {'STANDARD_INFLEXIBLE': 'N/A', 'FLOCK_DIRECT_INFLEXIBLE': 'N/A'}, 'N/A'

        result = {
            'SO': so,
            'Accessorials': so_data['Accessorials'],
            'Length (inch)': so_data['items'][0]['dimensions'].split('*')[0] if so_data['items'] else 0,
            'Width (inch)': so_data['items'][0]['dimensions'].split('*')[1] if so_data['items'] else 0,
            'Height (inch)': so_data['items'][0]['dimensions'].split('*')[2] if so_data['items'] else 0,
            'Weight': so_data['items'][0]['weight'] if so_data['items'] else 0,
            'Delivery Zip': so_data['zip'],
            'Pallet Number': so_data['items'][0]['pallets'] if so_data['items'] else 0,
            'Pick Up Date': so_data['pick_up_date'],
            'Delivery Service Type': so_data['delivery_ServiceType'],
            'Location Type': so_data['locationType'],
            'Has Pallet Jack and Forklift': 'Yes' if so_data['hasPalletJackAndForklift'] else 'No',
            'Shipment Service Type': so_data['shipment_ServiceType'],
            'Daylight': daylight_net_charge,
            'Daylight Class': daylight_class,
            'Auptix Class': freight_class,
            'Auptix Standard Inflexible': rates.get('STANDARD_INFLEXIBLE', 'N/A'),
            'Auptix Flock Direct Inflexible': rates.get('FLOCK_DIRECT_INFLEXIBLE', 'N/A'),
            'Warehouse Location': so_data['warehouseLocation']
        }
        results.append(result)

    return results

@app.route('/process_form', methods=['POST'])
def process_form():
    data = request.get_json()
    print(f"Received data: {data}")  # Log the received data for debugging

    if isinstance(data, list):
        so_grouped_data = {}
        for row in data:
            so = row.get('so', '').strip()  # Strip any leading or trailing whitespace from SO
            print(f"Processing SO: '{so}'")  # Log the SO to ensure it's being captured correctly
            if not so:
                print(f"Warning: Empty SO encountered in row: {row}")
                continue

            if so not in so_grouped_data:
                so_grouped_data[so] = {
                    'SO': so,
                    'Accessorials': row.get('accessorials', ''),
                    'zip': row.get('zip', ''),
                    'pick_up_date': row.get('pick_up_date', ''),
                    'delivery_ServiceType': row.get('delivery_ServiceType', ''),
                    'locationType': row.get('locationType', ''),
                    'hasPalletJackAndForklift': row.get('hasPalletJackAndForklift') == 'Yes',
                    'shipment_ServiceType': row.get('shipmentServiceType', ''),
                    'warehouseLocation': row.get('warehouseLocation', ''),
                    'items': []
                }

            # Calculate freight class here
            for item in row.get('cargoItems', []):
                length = int(item.get('length', 0))
                width = int(item.get('width', 0))
                height = int(item.get('height', 0))
                weight = int(item.get('weight', 0))
                freight_class = calculate_freight_class(weight, length, width, height)

                # Append the current item to the SO's list of items
                so_grouped_data[so]['items'].append({
                    "description": "General Merchandise",
                    "nmfcNumber": "",
                    "nmfcSubNumber": "",
                    "pcs": 0,
                    "pallets": item.get('palletNumber', 1),
                    "weight": weight,
                    "actualClass": freight_class,  # Setting actual class here
                    "dimensions": f"{length}*{width}*{height}",
                    "freightClass": f"CLASS_{freight_class}"  # Setting freight class here
                })

        # Call the process_quote function to process the data
        try:
            results = process_quote(so_grouped_data)
            return jsonify(results), 200
        except ValueError as e:
            return jsonify({"error": str(e)}), 500
    else:
        print("Warning: Received data is not a list")
        return jsonify({"error": "Invalid data format"}), 400

if __name__ == '__main__':
    app.run(debug=True)