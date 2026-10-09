"""
Airport list for the From/To autocomplete. TBO Search expects IATA city or
airport codes (e.g. DEL, BOM). Add more rows any time — the format is
(code, city, airport name, country code, country).
"""
AIRPORTS = [
    # India
    ("DEL", "Delhi", "Indira Gandhi International Airport", "IN", "India"),
    ("BOM", "Mumbai", "Chhatrapati Shivaji Maharaj International Airport", "IN", "India"),
    ("BLR", "Bengaluru", "Kempegowda International Airport", "IN", "India"),
    ("MAA", "Chennai", "Chennai International Airport", "IN", "India"),
    ("CCU", "Kolkata", "Netaji Subhas Chandra Bose International Airport", "IN", "India"),
    ("HYD", "Hyderabad", "Rajiv Gandhi International Airport", "IN", "India"),
    ("AMD", "Ahmedabad", "Sardar Vallabhbhai Patel International Airport", "IN", "India"),
    ("PNQ", "Pune", "Pune Airport", "IN", "India"),
    ("GOI", "Goa", "Dabolim Airport", "IN", "India"),
    ("GOX", "Goa", "Manohar International Airport (Mopa)", "IN", "India"),
    ("COK", "Kochi", "Cochin International Airport", "IN", "India"),
    ("TRV", "Thiruvananthapuram", "Trivandrum International Airport", "IN", "India"),
    ("CCJ", "Kozhikode", "Calicut International Airport", "IN", "India"),
    ("JAI", "Jaipur", "Jaipur International Airport", "IN", "India"),
    ("LKO", "Lucknow", "Chaudhary Charan Singh International Airport", "IN", "India"),
    ("VNS", "Varanasi", "Lal Bahadur Shastri International Airport", "IN", "India"),
    ("PAT", "Patna", "Jay Prakash Narayan Airport", "IN", "India"),
    ("IXC", "Chandigarh", "Chandigarh International Airport", "IN", "India"),
    ("ATQ", "Amritsar", "Sri Guru Ram Dass Jee International Airport", "IN", "India"),
    ("SXR", "Srinagar", "Sheikh ul-Alam International Airport", "IN", "India"),
    ("IXJ", "Jammu", "Jammu Airport", "IN", "India"),
    ("IXL", "Leh", "Kushok Bakula Rimpochee Airport", "IN", "India"),
    ("GAU", "Guwahati", "Lokpriya Gopinath Bordoloi International Airport", "IN", "India"),
    ("BBI", "Bhubaneswar", "Biju Patnaik International Airport", "IN", "India"),
    ("NAG", "Nagpur", "Dr. Babasaheb Ambedkar International Airport", "IN", "India"),
    ("IDR", "Indore", "Devi Ahilya Bai Holkar Airport", "IN", "India"),
    ("BHO", "Bhopal", "Raja Bhoj Airport", "IN", "India"),
    ("RPR", "Raipur", "Swami Vivekananda Airport", "IN", "India"),
    ("VTZ", "Visakhapatnam", "Visakhapatnam Airport", "IN", "India"),
    ("IXB", "Bagdogra", "Bagdogra Airport", "IN", "India"),
    ("IXR", "Ranchi", "Birsa Munda Airport", "IN", "India"),
    ("UDR", "Udaipur", "Maharana Pratap Airport", "IN", "India"),
    ("JDH", "Jodhpur", "Jodhpur Airport", "IN", "India"),
    ("STV", "Surat", "Surat Airport", "IN", "India"),
    ("BDQ", "Vadodara", "Vadodara Airport", "IN", "India"),
    ("IXE", "Mangaluru", "Mangaluru International Airport", "IN", "India"),
    ("CJB", "Coimbatore", "Coimbatore International Airport", "IN", "India"),
    ("IXM", "Madurai", "Madurai Airport", "IN", "India"),
    ("TRZ", "Tiruchirappalli", "Tiruchirappalli International Airport", "IN", "India"),
    ("IXZ", "Port Blair", "Veer Savarkar International Airport", "IN", "India"),
    ("DED", "Dehradun", "Jolly Grant Airport", "IN", "India"),
    ("GAY", "Gaya", "Gaya Airport", "IN", "India"),
    ("AGR", "Agra", "Agra Airport", "IN", "India"),
    ("IXA", "Agartala", "Maharaja Bir Bikram Airport", "IN", "India"),
    ("IMF", "Imphal", "Imphal International Airport", "IN", "India"),
    ("DIB", "Dibrugarh", "Dibrugarh Airport", "IN", "India"),
    ("NMI", "Navi Mumbai", "Navi Mumbai International Airport", "IN", "India"),
    ("HDO", "Ghaziabad", "Hindon Airport", "IN", "India"),
    # Middle East
    ("DXB", "Dubai", "Dubai International Airport", "AE", "United Arab Emirates"),
    ("DWC", "Dubai", "Al Maktoum International Airport", "AE", "United Arab Emirates"),
    ("AUH", "Abu Dhabi", "Zayed International Airport", "AE", "United Arab Emirates"),
    ("SHJ", "Sharjah", "Sharjah International Airport", "AE", "United Arab Emirates"),
    ("DOH", "Doha", "Hamad International Airport", "QA", "Qatar"),
    ("MCT", "Muscat", "Muscat International Airport", "OM", "Oman"),
    ("BAH", "Bahrain", "Bahrain International Airport", "BH", "Bahrain"),
    ("KWI", "Kuwait City", "Kuwait International Airport", "KW", "Kuwait"),
    ("JED", "Jeddah", "King Abdulaziz International Airport", "SA", "Saudi Arabia"),
    ("MED", "Madinah", "Prince Mohammad bin Abdulaziz Airport", "SA", "Saudi Arabia"),
    ("RUH", "Riyadh", "King Khalid International Airport", "SA", "Saudi Arabia"),
    ("DMM", "Dammam", "King Fahd International Airport", "SA", "Saudi Arabia"),
    # Asia
    ("SIN", "Singapore", "Changi Airport", "SG", "Singapore"),
    ("BKK", "Bangkok", "Suvarnabhumi Airport", "TH", "Thailand"),
    ("DMK", "Bangkok", "Don Mueang International Airport", "TH", "Thailand"),
    ("HKT", "Phuket", "Phuket International Airport", "TH", "Thailand"),
    ("KUL", "Kuala Lumpur", "Kuala Lumpur International Airport", "MY", "Malaysia"),
    ("DPS", "Bali", "Ngurah Rai International Airport", "ID", "Indonesia"),
    ("CGK", "Jakarta", "Soekarno-Hatta International Airport", "ID", "Indonesia"),
    ("HKG", "Hong Kong", "Hong Kong International Airport", "HK", "Hong Kong"),
    ("NRT", "Tokyo", "Narita International Airport", "JP", "Japan"),
    ("HND", "Tokyo", "Haneda Airport", "JP", "Japan"),
    ("ICN", "Seoul", "Incheon International Airport", "KR", "South Korea"),
    ("PEK", "Beijing", "Beijing Capital International Airport", "CN", "China"),
    ("PVG", "Shanghai", "Shanghai Pudong International Airport", "CN", "China"),
    ("SGN", "Ho Chi Minh City", "Tan Son Nhat International Airport", "VN", "Vietnam"),
    ("HAN", "Hanoi", "Noi Bai International Airport", "VN", "Vietnam"),
    ("MLE", "Male", "Velana International Airport", "MV", "Maldives"),
    ("CMB", "Colombo", "Bandaranaike International Airport", "LK", "Sri Lanka"),
    ("KTM", "Kathmandu", "Tribhuvan International Airport", "NP", "Nepal"),
    ("DAC", "Dhaka", "Hazrat Shahjalal International Airport", "BD", "Bangladesh"),
    ("PBH", "Paro", "Paro International Airport", "BT", "Bhutan"),
    # Europe
    ("LHR", "London", "Heathrow Airport", "GB", "United Kingdom"),
    ("LGW", "London", "Gatwick Airport", "GB", "United Kingdom"),
    ("MAN", "Manchester", "Manchester Airport", "GB", "United Kingdom"),
    ("CDG", "Paris", "Charles de Gaulle Airport", "FR", "France"),
    ("FRA", "Frankfurt", "Frankfurt Airport", "DE", "Germany"),
    ("MUC", "Munich", "Munich Airport", "DE", "Germany"),
    ("AMS", "Amsterdam", "Amsterdam Airport Schiphol", "NL", "Netherlands"),
    ("ZRH", "Zurich", "Zurich Airport", "CH", "Switzerland"),
    ("FCO", "Rome", "Leonardo da Vinci–Fiumicino Airport", "IT", "Italy"),
    ("MAD", "Madrid", "Adolfo Suárez Madrid–Barajas Airport", "ES", "Spain"),
    ("IST", "Istanbul", "Istanbul Airport", "TR", "Turkey"),
    ("VIE", "Vienna", "Vienna International Airport", "AT", "Austria"),
    # Americas / Oceania / Africa
    ("JFK", "New York", "John F. Kennedy International Airport", "US", "United States"),
    ("EWR", "Newark", "Newark Liberty International Airport", "US", "United States"),
    ("SFO", "San Francisco", "San Francisco International Airport", "US", "United States"),
    ("ORD", "Chicago", "O'Hare International Airport", "US", "United States"),
    ("IAD", "Washington", "Washington Dulles International Airport", "US", "United States"),
    ("LAX", "Los Angeles", "Los Angeles International Airport", "US", "United States"),
    ("YYZ", "Toronto", "Toronto Pearson International Airport", "CA", "Canada"),
    ("YVR", "Vancouver", "Vancouver International Airport", "CA", "Canada"),
    ("SYD", "Sydney", "Sydney Kingsford Smith Airport", "AU", "Australia"),
    ("MEL", "Melbourne", "Melbourne Airport", "AU", "Australia"),
    ("AKL", "Auckland", "Auckland Airport", "NZ", "New Zealand"),
    ("JNB", "Johannesburg", "O. R. Tambo International Airport", "ZA", "South Africa"),
    ("NBO", "Nairobi", "Jomo Kenyatta International Airport", "KE", "Kenya"),
    ("CAI", "Cairo", "Cairo International Airport", "EG", "Egypt"),
]

_BY_CODE = {a[0]: a for a in AIRPORTS}


def as_dict(row) -> dict:
    code, city, name, cc, country = row
    return {"code": code, "city": city, "name": name, "country_code": cc, "country": country}


def search_airports(q: str, limit: int = 10) -> list:
    q = (q or "").strip().lower()
    if not q:
        return [as_dict(a) for a in AIRPORTS[:limit]]
    exact, starts, contains = [], [], []
    for a in AIRPORTS:
        code, city, name, _cc, country = a
        if code.lower() == q:
            exact.append(a)
        elif city.lower().startswith(q) or name.lower().startswith(q):
            starts.append(a)
        elif q in city.lower() or q in name.lower() or q in country.lower():
            contains.append(a)
    return [as_dict(a) for a in (exact + starts + contains)[:limit]]


def country_of(code: str) -> str:
    row = _BY_CODE.get((code or "").upper())
    return row[3] if row else ""


def city_of(code: str) -> str:
    row = _BY_CODE.get((code or "").upper())
    return row[1] if row else code
