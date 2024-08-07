from flask import Flask, request, jsonify, stream_with_context, Response
import pandas as pd
import json
import os
from rate_quote import RateQuoteAPI, AuptixRateQuoteAPI
from flask_cors import CORS
import time

app = Flask(__name__)
CORS(app)

data_queue = []

def load_config():
    with open('config.json', 'r') as file:
        return json.load(file)

def clean_measurement(measurement):
    measurement = measurement.replace('\n', '').replace('\r', '').strip()
    parts = measurement.split('*')
    if len(parts) != 3:
        raise ValueError(f"Invalid measurement format: {measurement}")
    return [int(float(part)) for part in parts]

def calculate_freight_class(weight, length, width, height, pallet):
    volume = (length * width * height) / 1728
    density = weight / pallet / volume

    if density >= 50:
        freight_class = '50'
    elif density >= 35:
        freight_class = '55'
    elif density >= 30:
        freight_class = '60'
    elif density >= 22.5:
        freight_class = '65'
    elif density >= 15:
        freight_class = '70'
    elif density >= 13.5:
        freight_class = '77.5'
    elif density >= 12:
        freight_class = '85'
    elif density >= 10.5:
        freight_class = '92.5'
    elif density >= 9:
        freight_class = '100'
    elif density >= 8:
        freight_class = '110'
    elif density >= 7:
        freight_class = '125'
    elif density >= 6:
        freight_class = '150'
    elif density >= 5:
        freight_class = '175'
    elif density >= 4:
        freight_class = '200'
    elif density >= 3:
        freight_class = '250'
    elif density >= 2:
        freight_class = '300'
    elif density >= 1:
        freight_class = '400'
    else:
        freight_class = '500'
    
    return freight_class

def parse_daylight_response(response):
    try:
        if 'dyltRateQuoteResp' in response:
            net_charge = response['dyltRateQuoteResp']['totalCharges']['netCharge']
            freight_class = response['dyltRateQuoteResp']['itemCharges']['itemCharge'][0]['actualClass']
        else:
            raise ValueError("Unexpected response structure")
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
    return [{'accId': acc_id.strip(), 'accName': mapping.get(acc_id.strip(), 'Other/O')} for acc_id in accessorials]

def process_daylight_quote(so_data, items, mapped_accessorials, daylight_api):
    pickup_date_str = so_data['pick_up_date']
    daylight_payload = {
        "dyltRateQuoteReq": {
            "accountNumber": "21818977",
            "userName": "LINKTRANS",
            "password": "daylight",
            "billTerms": "PP",
            "serviceType": "LTL",
            "pickupDate": pickup_date_str,
            "shipperInfo": {
                "customerNumber": "21818977",
                "customerName": "Linktrans",
                "customerAddress": {
                    "streetAddress": "14650 Meyer Canyon Dr, DOCK 1203",
                    "aptAddress": "",
                    "city": "Fontana",
                    "state": "CA",
                    "zip": "92336"
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

def process_auptix_quote(so_data, item_data, length, width, height, weight, actual_class, auptix_api):
    pickup_date_str = so_data['pick_up_date']
    auptix_payload = {
        "shipment": {
            "pickupDate": pickup_date_str,
            "pickUpStopDetails": {
                "postalCode": "92336",
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
                "hasPalletJackAndForklift": so_data.get('hasPalletJackAndForklift', False),
                "schedulingService": {
                    "type": so_data.get('delivery_ServiceType', 'CALL_FOR_APPOINTMENT'),
                    "date": pickup_date_str,
                    "startTime": "09:00",
                    "endTime": "16:00"
                }
            },
            "shipmentItems": [
                {
                    "quantity": item_data['pallet number'],
                    "packagingType": "PALLET",
                    "dimensions": {
                        "lengthIn": length,
                        "widthIn": width,
                        "heightIn": height
                    },
                    "stackable": False,
                    "turnable": True,
                    "totalWeightLbs": int(weight/int(item_data['pallet number'])),
                    "freightClass": f"CLASS_{str(actual_class).replace('.', '_')}",
                    "description": "General Merchandise"
                }
            ],
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
    except Exception as e:
        print(f"Error occurred while processing Auptix API: {e}")
        return {'STANDARD_INFLEXIBLE': 'pending', 'FLOCK_DIRECT_INFLEXIBLE': 'pending'}, 'N/A'

@app.route('/process_excel', methods=['POST'])
def process_excel():
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    if not file:
        return jsonify({"error": "No file provided"}), 400

    try:
        df = pd.read_excel(file)
        data_queue.append(df)
        return jsonify({"message": "File uploaded successfully. Processing started."}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/process_form', methods=['POST'])
def process_form():
    data = request.get_json()

    # Print received data for debugging
    print("Received form data:", data)

    so_data = {
        'SO': data.get('so'),
        'Accessorials': ','.join(data.get('accessorials', [])),
        'length': data.get('length'),
        'width': data.get('width'),
        'height': data.get('height'),
        'weight': data.get('weight'),
        'zip': data.get('zip'),
        'pallet number': data.get('palletNumber'),
        'pick_up_date': data.get('pickUpDate'),
        'delivery_ServiceType': data.get('deliveryServiceType'),
        'locationType': data.get('locationType'),
        'hasPalletJackAndForklift': data.get('hasPalletJackAndForklift') == 'Yes',
        'shipment_ServiceType': data.get('shipmentServiceType')
    }

    length, width, height = int(so_data['length']), int(so_data['width']), int(so_data['height'])
    weight = int(so_data['weight'])
    actual_class = calculate_freight_class(weight, length, width, height, int(so_data['pallet number']))

    items = [{
        "description": "General Merchandise",
        "nmfcNumber": "",
        "nmfcSubNumber": "",
        "pcs": 0,
        "pallets": so_data['pallet number'],
        "weight": weight,
        "actualClass": str(actual_class),
        "dimensions": f"{length}*{width}*{height}"
    }]

    config = load_config()
    daylight_api = RateQuoteAPI(config['daylight'])
    auptix_api = AuptixRateQuoteAPI(config['auptix'])

    mapped_accessorials = map_accessorials(so_data['Accessorials'].split(','))

    daylight_net_charge, daylight_class = process_daylight_quote(so_data, items, mapped_accessorials, daylight_api)
    auptix_rates, auptix_class = process_auptix_quote(so_data, so_data, length, width, height, weight, actual_class, auptix_api)

    result = {
        'SO': so_data['SO'],
        'Accessorials': so_data['Accessorials'],
        'Length (inch)': length,
        'Width (inch)': width,
        'Height (inch)': height,
        'Weight': weight,
        'Delivery Zip': so_data['zip'],
        'Pallet Number': so_data['pallet number'],
        'Pick Up Date': so_data['pick_up_date'],
        'Delivery Service Type': so_data['delivery_ServiceType'],
        'Location Type': so_data['locationType'],
        'Has Pallet Jack and Forklift': 'Yes' if so_data['hasPalletJackAndForklift'] else 'No',
        'Shipment Service Type': so_data['shipment_ServiceType'],
        'Daylight': daylight_net_charge,
        'Daylight Class': daylight_class,
        'Auptix Class': auptix_class,
        'Auptix Standard Inflexible': auptix_rates.get('STANDARD_INFLEXIBLE', 'N/A'),
        'Auptix Flock Direct Inflexible': auptix_rates.get('FLOCK_DIRECT_INFLEXIBLE', 'N/A')
    }

    return jsonify(result)

if __name__ == '__main__':
    app.run(debug=True)
