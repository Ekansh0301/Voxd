from tars.tools.forms import _fields_on_page, _value, match_field

PROFILE = {
    "name": "Ravi Kumar",
    "email": "ravi@example.com",
    "phone": "9876543210",
    "roll_number": "2021101",
    "college": "IIIT",
}


def test_labels_map_to_profile():
    assert match_field("Email ID *", PROFILE) == "email"
    assert match_field("Mobile Number", PROFILE) == "phone"
    assert match_field("Roll No.", PROFILE) == "roll_number"
    assert match_field("Name of Institute", PROFILE) == "college"
    assert match_field("Full Name", PROFILE) == "name"
    assert (
        match_field("First name", PROFILE) == "first_name"
        and _value("first_name", PROFILE) == "Ravi"
    )
    assert _value("last_name", PROFILE) == "Kumar"


def test_sensitive_and_unknown_fields_left_alone():
    assert match_field("Password", PROFILE) is None
    assert match_field("Card number", PROFILE) is None
    assert match_field("Aadhaar number", PROFILE) is None
    assert match_field("Why do you want to join?", PROFILE) is None
    assert match_field("City", PROFILE) is None  # not in the profile


def test_fields_from_snapshot():
    snap = 'https://x\nheading "Register"\ninput "Full Name"\ntextbox "Email ID"\nbutton "Submit"\nfield "Mobile Number"'
    assert _fields_on_page(snap) == ["Full Name", "Email ID", "Mobile Number"]


def test_unnamed_duplicates_dropped():
    snap = 'https://x\ninput "unnamed input"\ninput "Full Name"\nfield "Email ID"'
    assert _fields_on_page(snap) == ["Full Name", "Email ID"]
