import os
import json
import pandas as pd
import time
from datetime import datetime, timedelta
from rate_quote import RateQuoteAPI, AuptixRateQuoteAPI

def load_config():
    with open('config.json', 'r') as file:
        return json.load(file)

def clean_measurement(measurement):
    """Clean measurement value and convert to int."""
    measurement = measurement.replace('\n', '').replace('\r', '').strip()
    parts = measurement.split('*')
    if len(parts) != 3:
        raise ValueError(f"Invalid measurement format: {measurement}")
    return [int(float(part)) for part in parts]

def calculate_freight_class(weight, length, width, height, pallet):
    volume = (length * width * height) / 1728  # Convert cubic inches to cubic feet
    density = weight / pallet / volume
    
    # Determine freight class based on density
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

def find_excel_file():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    for file in os.listdir(current_dir):
        if file.endswith('.xlsx') and '报价' in file:
            return os.path.join(current_dir, file)
    return None

def parse_daylight_response(response):
    try:
        print(f"Raw Daylight response: {response}")  # Debug statement
        if isinstance(response, str):
            response = json.loads(response)
        net_charge = response.get('dyltRateQuoteResp', {}).get('totalCharges', {}).get('netCharge', 'N/A')
        daylight_class = response.get('dyltRateQuoteResp', {}).get('itemCharges', {}).get('itemCharge', [{}])[0].get('actualClass', 'N/A')
    except json.JSONDecodeError as e:
        print(f"Error parsing Daylight JSON response: {e}")
        net_charge = 'N/A'
        daylight_class = 'N/A'
    return net_charge, daylight_class

def parse_auptix_response(response):
    rates = {}
    try:
        for option in response.get('fulfillmentOptions', []):
            print(f"Checking option: {option}")  # Debug statement
            service_level = option['serviceLevel']
            pickup_flexibility = option['pickupFlexibility']
            field_name = f"{service_level}_{pickup_flexibility}".upper()
            rates[field_name] = option['totalRateUsd']
        auptix_class = response['shipment']['shipmentItems'][0]['freightClass']
        if isinstance(auptix_class, str):
            auptix_class = auptix_class.replace('.', '_')
    except Exception as e:
        print(f"Error parsing Auptix JSON response: {e}")
        auptix_class = 'N/A'
    for key, value in rates.items():
        print(f"Extracted rate: {key} = {value}")  # Debug statement
    return rates, auptix_class

def process_excel():
    config = load_config()
    daylight_api = RateQuoteAPI(config['daylight'])
    auptix_api = AuptixRateQuoteAPI(config['auptix'])

    file_path = find_excel_file()
    if not file_path:
        print("No Excel file found with '报价' in the name.")
        return

    df = pd.read_excel(file_path, dtype={'zip': str}).fillna('')

    # Accessorials mapping
    accid_to_accname = {
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
        'Compliance Services Fee': 'Other'
    }

    try:
        grouped = df.groupby('SO')
        results = []
        for so, group in grouped:
            so_data = group.iloc[0].to_dict()
            items = []
            for _, row in group.iterrows():
                item_data = row.to_dict()
                try:
                    length, width, height = clean_measurement(item_data['mesurement'])
                except ValueError as e:
                    print(f"Error parsing measurement for SO {item_data['SO']}: {e}")
                    continue
                weight = item_data['weight']
                actual_class = calculate_freight_class(weight, length, width, height, item_data['pallet number'])
                items.append({
                    "description": "General Merchandise",
                    "nmfcNumber": "",
                    "nmfcSubNumber": "",
                    "pcs": 0,
                    "pallets": item_data['pallet number'],
                    "weight": weight,
                    "actualClass": str(actual_class),
                    "dimensions": f"{length}*{width}*{height}"  # Include dimensions as int
                })
            
            if items:
                print(f"Processing SO: {so}")
                pickup_date_str = so_data['pick_up_date'].strftime('%Y-%m-%d')  # Convert to string

                # Get Accessorials from the Excel file and map them
                accessorials = so_data['Accessorials'].split(',')
                mapped_accessorials = [{"accId": acc_id.strip(), "accName": accid_to_accname.get(acc_id.strip(), "")} for acc_id in accessorials]

                # 构建Daylight API payload
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
                print(f"Daylight Payload for SO {so}: {json.dumps(daylight_payload, indent=2)}")
                try:
                    daylight_response = daylight_api.get_rate_quote(daylight_payload)
                    print(f"Daylight Rate Quote Response for SO {so}: {daylight_response}")
                    daylight_net_charge, daylight_class = parse_daylight_response(daylight_response)
                    if isinstance(daylight_class, str):
                        daylight_class = daylight_class.replace('.', '_')
                    print(f"Daylight Rate Quote Data for SO {so}: {daylight_net_charge}, {daylight_class}")
                except Exception as e:
                    print(f"Error occurred while processing Daylight API for SO {so}: {e}")
                    daylight_net_charge = 'N/A'
                    daylight_class = 'N/A'

                time.sleep(10)  # Add 10-second delay between API calls

                # 构建Auptix API payload
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
                                "totalWeightLbs": weight,
                                "freightClass": f"CLASS_{str(actual_class).replace('.', '_')}",
                                "description": "General Merchandise"
                            }
                        ],
                        "additionalServices": {
                            "reeferProhibited": True
                        }
                    }
                }
                print(f"Auptix Payload for SO {so}: {json.dumps(auptix_payload, indent=2)}")
                try:
                    auptix_response = auptix_api.get_rate_quote(auptix_payload)
                    print(f"Auptix Rate Quote Response for SO {so}: {auptix_response}")
                    if isinstance(auptix_response, str):
                        auptix_response = json.loads(auptix_response)
                    auptix_rates, auptix_class = parse_auptix_response(auptix_response)
                    if 'STANDARD_INFLEXIBLE' not in auptix_rates:
                        auptix_rates['STANDARD_INFLEXIBLE'] = 'pending'
                    if 'FLOCK_DIRECT_INFLEXIBLE' not in auptix_rates:
                        auptix_rates['FLOCK_DIRECT_INFLEXIBLE'] = 'pending'
                    print(f"Auptix Rate Quote Data for SO {so}: {auptix_rates}")
                except Exception as e:
                    print(f"Error occurred while processing Auptix API for SO {so}: {e}")
                    auptix_rates = {'STANDARD_INFLEXIBLE': 'pending', 'FLOCK_DIRECT_INFLEXIBLE': 'pending'}
                    auptix_class = 'N/A'

                result = {
                    'SO': so_data.get('SO', ''),
                    'Accessorials': ', '.join(accessorials),
                    'street Address': so_data.get('street Address', 'N/A'),
                    'city': so_data.get('city', 'N/A'),
                    'state': so_data.get('state', 'N/A'),
                    'zip': so_data.get('zip', 'N/A'),
                    'mesurement': f"{length}*{width}*{height}",
                    'weight': weight,
                    'pallet number': item_data.get('pallet number', 'N/A'),
                    'daylight': daylight_net_charge,
                    'daylight_class': f"CLASS_{daylight_class}",
                    'auptix_class': auptix_class
                }

                for rate_type, rate_value in auptix_rates.items():
                    result[f'auptix_{rate_type.lower()}'] = rate_value

                results.append(result)
        
        # 将results写入到新的Excel文件中
        results_df = pd.DataFrame(results)
        output_file_path = os.path.join(os.path.dirname(file_path), 'LTL报价汇总.xlsx')
        results_df.to_excel(output_file_path, index=False)
        print(f"Processed data saved to {output_file_path}.")
        
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    process_excel()
