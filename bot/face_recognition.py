"""
نسخه ساده تشخیص چهره
برای production می‌تونید face_recognition واقعی نصب کنید
"""

def encode_face_from_bytes(image_bytes):
    """نسخه موقت - بدون face_recognition"""
    print("⚠️ Face recognition not installed - using placeholder")
    return None


def encode_face_from_file(image_file):
    """نسخه موقت - بدون face_recognition"""
    print("⚠️ Face recognition not installed - using placeholder")
    return None


def compare_faces(known_encoding, unknown_encoding, tolerance=0.5):
    """نسخه موقت"""
    return False, 0


def find_matching_student(face_encoding, students, tolerance=0.5):
    """نسخه موقت - هنرجو رو با کد پیدا میکنیم"""
    return None, 0حغ