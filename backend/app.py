from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, Response, make_response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import cv2
import os
import pyotp
import numpy as np
from werkzeug.security import generate_password_hash, check_password_hash
import pickle
import base64
import io
from PIL import Image
import time
import logging
from sqlalchemy import inspect
import random
import string
from flask_login import login_required
import json
import socket
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
from reportlab.lib.utils import ImageReader
import qrcode
from reportlab.lib.colors import HexColor
from blockchain import Blockchain
import hashlib
import os

# Configure paths for frontend separate from backend
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), 'frontend')

app = Flask(__name__, 
            static_folder=os.path.join(FRONTEND_DIR, 'static'), 
            template_folder=os.path.join(FRONTEND_DIR, 'templates'))
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///voting_system.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable caching for development

# Initialize face detection
face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
profile_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_profileface.xml')

db = SQLAlchemy(app)

# Initialize blockchain
blockchain = Blockchain()

# Database Models
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(120), nullable=False)
    totp_secret = db.Column(db.String(32), nullable=False)

class Voter(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    voter_id = db.Column(db.String(10), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    phone = db.Column(db.String(15), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    address = db.Column(db.Text, nullable=False)
    district = db.Column(db.String(50), nullable=False)
    state = db.Column(db.String(50), nullable=False)
    aadhar_number = db.Column(db.String(12), unique=True, nullable=False)
    education = db.Column(db.String(50))
    occupation = db.Column(db.String(50))
    is_disabled = db.Column(db.Boolean, default=False)
    photo_data = db.Column(db.Text)
    fingerprint_data = db.Column(db.Text)
    has_voted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    face_data = db.Column(db.PickleType, nullable=True)
    last_attempt = db.Column(db.DateTime, nullable=True)
    registration_ip = db.Column(db.String(45))
    last_login_ip = db.Column(db.String(45))

class Candidate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    party = db.Column(db.String(100), nullable=False)
    photo_path = db.Column(db.String(200), nullable=True)
    votes = db.Column(db.Integer, default=0)

class ScannerSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(50), unique=True, nullable=False)
    fingerprint_data = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, completed, error
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)

def preprocess_image(image):
    """Preprocess the image for better face detection while maintaining quality"""
    try:
        # Convert to grayscale for detection only
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Apply minimal preprocessing to maintain quality
        gray = cv2.equalizeHist(gray)
        
        # Enhance contrast using CLAHE with gentle parameters
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        gray = clahe.apply(gray)
        
        return gray
    except Exception as e:
        print(f"Error in image preprocessing: {str(e)}")
        return None

def detect_face(frame):
    """Detect face using OpenCV's face detection with improved quality preservation"""
    try:
        # Make a copy of the original frame
        original_frame = frame.copy()
        
        # Preprocess image for detection only
        gray = preprocess_image(frame)
        if gray is None:
            print("Error: Image preprocessing failed")
            return None, None
        
        # Print image dimensions for debugging
        print(f"Processing image with dimensions: {frame.shape}")
        
        # Try different detection parameters with both frontal and profile face cascades
        detection_params = [
            {'scaleFactor': 1.1, 'minNeighbors': 5, 'minSize': (100, 100)},  # Strict
            {'scaleFactor': 1.05, 'minNeighbors': 3, 'minSize': (80, 80)},   # Balanced
            {'scaleFactor': 1.15, 'minNeighbors': 2, 'minSize': (60, 60)}    # Lenient
        ]
        
        # Try frontal face detection first
        faces = []
        for params in detection_params:
            faces = face_cascade.detectMultiScale(
                gray,
                scaleFactor=params['scaleFactor'],
                minNeighbors=params['minNeighbors'],
                minSize=params['minSize']
            )
            if len(faces) > 0:
                break
        
        # If no frontal face found, try profile face detection
        if len(faces) == 0:
            for params in detection_params:
                faces = profile_cascade.detectMultiScale(
                    gray,
                    scaleFactor=params['scaleFactor'],
                    minNeighbors=params['minNeighbors'],
                    minSize=params['minSize']
                )
                if len(faces) > 0:
                    break
                # Try flipped image for profile detection from other side
                flipped = cv2.flip(gray, 1)
                faces = profile_cascade.detectMultiScale(
                    flipped,
                    scaleFactor=params['scaleFactor'],
                    minNeighbors=params['minNeighbors'],
                    minSize=params['minSize']
                )
                if len(faces) > 0:
                    # Adjust coordinates for flipped image
                    faces = [(gray.shape[1] - x - w, y, w, h) for (x, y, w, h) in faces]
                    break
        
        if len(faces) == 0:
            print("No faces detected in the frame")
            return None, None
        
        # Get the largest face
        face_sizes = [w * h for (x, y, w, h) in faces]
        largest_face_idx = face_sizes.index(max(face_sizes))
        x, y, w, h = faces[largest_face_idx]
        
        # Add padding to face crop (proportional to face size)
        padding_percent = 0.3  # 30% padding
        padding_x = int(w * padding_percent)
        padding_y = int(h * padding_percent)
        
        # Calculate padded coordinates with bounds checking
        x1 = max(0, x - padding_x)
        y1 = max(0, y - padding_y)
        x2 = min(frame.shape[1], x + w + padding_x)
        y2 = min(frame.shape[0], y + h + padding_y)
        
        # Crop face region from the original frame
        face_img = original_frame[y1:y2, x1:x2]
        
        # Calculate the desired size while maintaining aspect ratio
        aspect_ratio = face_img.shape[1] / face_img.shape[0]
        target_height = 300  # Increased size for better quality
        target_width = int(target_height * aspect_ratio)
        
        # Resize with high-quality interpolation
        face_img = cv2.resize(face_img, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
        
        # Enhance the image quality
        face_img = cv2.fastNlMeansDenoisingColored(face_img, None, 5, 5, 7, 21)
        
        # Convert to BGR if not already
        if len(face_img.shape) == 2:
            face_img = cv2.cvtColor(face_img, cv2.COLOR_GRAY2BGR)
        
        print(f"Face detected and processed with size: {face_img.shape}")
        return face_img, (x, y, w, h)
        
    except Exception as e:
        print(f"Error in face detection: {str(e)}")
        return None, None

def compare_faces(face1, face2):
    """Compare two face images using multiple comparison methods with improved accuracy"""
    if face1 is None or face2 is None:
        print("One or both faces are None")
        return 0.0
    
    try:
        # Ensure both images are in BGR format
        if len(face1.shape) == 2:
            face1 = cv2.cvtColor(face1, cv2.COLOR_GRAY2BGR)
        if len(face2.shape) == 2:
            face2 = cv2.cvtColor(face2, cv2.COLOR_GRAY2BGR)
        
        # Resize images to same size while maintaining aspect ratio
        target_height = 300
        aspect_ratio = face1.shape[1] / face1.shape[0]
        target_width = int(target_height * aspect_ratio)
        
        face1 = cv2.resize(face1, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
        face2 = cv2.resize(face2, (target_width, target_height), interpolation=cv2.INTER_LANCZOS4)
        
        # Convert to grayscale for comparison
        face1_gray = cv2.cvtColor(face1, cv2.COLOR_BGR2GRAY)
        face2_gray = cv2.cvtColor(face2, cv2.COLOR_BGR2GRAY)
        
        # Apply histogram equalization
        face1_gray = cv2.equalizeHist(face1_gray)
        face2_gray = cv2.equalizeHist(face2_gray)
        
        # Calculate structural similarity index (SSIM)
        ssim_score = cv2.matchTemplate(face1_gray, face2_gray, cv2.TM_CCOEFF_NORMED)[0][0]
        
        # Calculate histogram similarity
        hist1 = cv2.calcHist([face1_gray], [0], None, [256], [0, 256])
        hist2 = cv2.calcHist([face2_gray], [0], None, [256], [0, 256])
        hist1 = cv2.normalize(hist1, hist1).flatten()
        hist2 = cv2.normalize(hist2, hist2).flatten()
        hist_score = cv2.compareHist(hist1, hist2, cv2.HISTCMP_CORREL)
        
        # Calculate feature matching score using ORB
        orb = cv2.ORB_create()
        kp1, des1 = orb.detectAndCompute(face1_gray, None)
        kp2, des2 = orb.detectAndCompute(face2_gray, None)
        
        if des1 is not None and des2 is not None:
            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
            matches = bf.match(des1, des2)
            matches = sorted(matches, key=lambda x: x.distance)
            feature_score = 1 - min(1.0, sum(m.distance for m in matches[:10]) / (100 * len(matches[:10])))
        else:
            feature_score = 0.0
        
        # Combine scores with adjusted weights
        final_score = (
            ssim_score * 0.4 +      # Structural similarity (40% weight)
            hist_score * 0.3 +      # Histogram similarity (30% weight)
            feature_score * 0.3     # Feature matching (30% weight)
        )
        
        print(f"Face comparison scores:")
        print(f"SSIM: {ssim_score:.3f}")
        print(f"Histogram: {hist_score:.3f}")
        print(f"Feature: {feature_score:.3f}")
        print(f"Final: {final_score:.3f}")
        
        return final_score
        
    except Exception as e:
        print(f"Error in face comparison: {str(e)}")
        return 0.0

def generate_voter_id():
    """Generate a simple voter ID: 3 letters followed by 3 numbers"""
    letters = ''.join(random.choices(string.ascii_uppercase, k=3))
    numbers = ''.join(random.choices(string.digits, k=3))
    return f"{letters}{numbers}"

def generate_voter_id_card(voter):
    # Create a BytesIO buffer for the PDF
    buffer = BytesIO()
    
    # Create the PDF object using the buffer and A4 size
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Define colors
    primary_color = HexColor('#1a237e')  # Dark blue
    secondary_color = HexColor('#303f9f')  # Medium blue
    
    # Add a border with rounded corners
    c.setStrokeColor(primary_color)
    c.setLineWidth(2)
    c.roundRect(50, height - 400, width - 100, 300, 10)
    
    # Add header with background
    c.setFillColor(primary_color)
    c.rect(50, height - 150, width - 100, 50, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(width/2, height - 130, "VOTER IDENTIFICATION CARD")
    
    # Add official seal
    c.setStrokeColor(secondary_color)
    c.setFillColor(colors.white)
    c.circle(width/2, height - 200, 30, fill=0)
    c.setFont("Helvetica", 8)
    c.setFillColor(secondary_color)
    c.drawCentredString(width/2, height - 202, "OFFICIAL SEAL")
    
    # Add voter photo if available
    if voter.photo_data:
        try:
            img_data = base64.b64decode(voter.photo_data)
            img_buffer = BytesIO(img_data)
            # Draw photo with border
            c.setStrokeColor(secondary_color)
            c.rect(80, height - 350, 100, 120, fill=0)
            c.drawImage(ImageReader(img_buffer), 80, height - 350, width=100, height=120)
        except Exception as e:
            print(f"Error adding photo to ID card: {str(e)}")
    
    # Generate QR code with voter information
    qr_data = {
        'voter_id': voter.voter_id,
        'name': voter.name,
        'aadhar': voter.aadhar_number
    }
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(json.dumps(qr_data))
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    
    # Save QR code to buffer and add to PDF
    qr_buffer = BytesIO()
    qr_img.save(qr_buffer)
    qr_buffer.seek(0)
    c.drawImage(ImageReader(qr_buffer), 80, height - 380, width=50, height=50)
    
    # Add voter details with improved layout
    c.setFillColor(colors.black)
    details_start_y = height - 250
    left_column = 250
    right_column = 350
    
    # Function to add detail row
    def add_detail_row(label, value, y_pos):
        c.setFont("Helvetica-Bold", 12)
        c.setFillColor(secondary_color)
        c.drawString(left_column, y_pos, label)
        c.setFont("Helvetica", 12)
        c.setFillColor(colors.black)
        
        # Handle multiline text for address
        if label == "Address:":
            words = value.split()
            lines = []
            current_line = []
            for word in words:
                current_line.append(word)
                if len(" ".join(current_line)) > 30:
                    lines.append(" ".join(current_line[:-1]))
                    current_line = [word]
            if current_line:
                lines.append(" ".join(current_line))
            
            for i, line in enumerate(lines):
                c.drawString(right_column, y_pos - (i * 15), line)
            return len(lines) * 15
        else:
            c.drawString(right_column, y_pos, str(value))
            return 20
    
    # Add details with consistent spacing
    y_pos = details_start_y
    details = [
        ("Voter ID:", voter.voter_id),
        ("Name:", voter.name),
        ("Age:", str(voter.age)),
        ("Gender:", voter.gender),
        ("Address:", voter.address),
        ("District:", voter.district),
        ("State:", voter.state),
        ("Phone:", voter.phone)
    ]
    
    for label, value in details:
        offset = add_detail_row(label, value, y_pos)
        y_pos -= offset
    
    # Add footer with improved styling
    c.setFillColor(secondary_color)
    c.setFont("Helvetica", 8)
    footer_text = "This card is issued by the Election Commission and is valid for identification purposes only."
    c.drawCentredString(width/2, height - 390, footer_text)
    
    # Add issue date
    c.setFont("Helvetica-Bold", 8)
    issue_date = datetime.now().strftime("%d-%m-%Y")
    c.drawRightString(width - 60, height - 380, f"Issue Date: {issue_date}")
    
    # Save the PDF
    c.save()
    buffer.seek(0)
    return buffer

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        admin = Admin.query.filter_by(username=username).first()
        
        if admin and check_password_hash(admin.password, password):
            session['admin_id'] = admin.id
            return redirect(url_for('admin_dashboard'))
        flash('Invalid credentials')
    return render_template('admin_login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    
    try:
        # Get page number for pagination
        page = request.args.get('page', 1, type=int)
        per_page = 10

        # Get voters with pagination
        voters = Voter.query.order_by(Voter.created_at.desc()).paginate(page=page, per_page=per_page)
        
        # Get statistics
        stats = get_voter_statistics()
        
        # Get total candidates
        total_candidates = Candidate.query.count()

        return render_template('admin_dashboard.html',
                             voters=voters,
                             stats=stats,
                             total_candidates=total_candidates)
                             
    except Exception as e:
        print(f"Error in admin dashboard: {str(e)}")
        flash('An error occurred while loading the dashboard', 'error')
        return redirect(url_for('admin_login'))

@app.route('/scanner', methods=['GET', 'POST'])
def scanner_page():
    if request.method == 'POST':
        try:
            # Generate a unique session ID
            session_id = ''.join(random.choices(string.ascii_letters + string.digits, k=20))
            
            # Create a new scanner session
            scanner_session = ScannerSession(
                session_id=session_id,
                expires_at=datetime.utcnow() + timedelta(minutes=5)
            )
            db.session.add(scanner_session)
            db.session.commit()
            
            return jsonify({
                'success': True,
                'sessionId': session_id
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': str(e)
            })
    
    return render_template('mobile_scanner.html')

@app.route('/scanner/status/<session_id>')
def scanner_status(session_id):
    session = ScannerSession.query.filter_by(session_id=session_id).first()
    if not session:
        return jsonify({'status': 'error', 'message': 'Session not found'})
    
    if datetime.utcnow() > session.expires_at:
        return jsonify({'status': 'error', 'message': 'Session expired'})
    
    return jsonify({
        'status': session.status,
        'message': 'Session active' if session.status == 'pending' else None
    })

@app.route('/scanner/submit', methods=['POST'])
def scanner_submit():
    try:
        data = request.get_json()
        session_id = data.get('sessionId')
        fingerprint_data = data.get('fingerprintData')
        
        if not session_id or not fingerprint_data:
            return jsonify({'success': False, 'message': 'Missing required data'})
        
        session = ScannerSession.query.filter_by(session_id=session_id).first()
        if not session:
            return jsonify({'success': False, 'message': 'Session not found'})
        
        if datetime.utcnow() > session.expires_at:
            return jsonify({'success': False, 'message': 'Session expired'})
        
        session.fingerprint_data = json.dumps(fingerprint_data)
        session.status = 'completed'
        db.session.commit()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/voter/register', methods=['GET', 'POST'])
def voter_registration():
    if request.method == 'POST':
        try:
            name = request.form.get('name_reg')
            age = int(request.form.get('age_reg'))
            gender = request.form.get('gender_reg')
            phone = request.form.get('phone_reg')
            email = request.form.get('email_reg')
            address = request.form.get('address_reg')
            district = request.form.get('district_reg')
            state = request.form.get('state_reg')
            aadhar_number = request.form.get('aadhar_number_reg')
            photo_data = request.form.get('photo')

            if not all([name, age, gender, phone, email, address, district, state, aadhar_number]):
                return jsonify({
                    'status': 'error',
                    'message': 'Please fill in all required fields.'
                }), 400

            if not photo_data:
                return jsonify({
                    'status': 'error',
                    'message': 'Please provide a photo for registration.'
                }), 400

            try:
                # Remove data URL prefix if present
                if 'data:image' in photo_data:
                    photo_data = photo_data.split(',')[1]

                # Convert base64 image to numpy array
                photo_bytes = base64.b64decode(photo_data)
                photo_array = np.frombuffer(photo_bytes, dtype=np.uint8)
                frame = cv2.imdecode(photo_array, cv2.IMREAD_COLOR)

                if frame is None:
                    return jsonify({
                        'status': 'error',
                        'message': 'Invalid image format. Please try again with a different photo.'
                    }), 400

                # Resize image if too large
                max_size = 1024
                height, width = frame.shape[:2]
                if height > max_size or width > max_size:
                    scale = max_size / max(height, width)
                    frame = cv2.resize(frame, None, fx=scale, fy=scale)

                # Detect face in the photo
                face_img, face_coords = detect_face(frame)
                
                if face_img is None:
                    return jsonify({
                        'status': 'error',
                        'message': 'No face detected in the photo. Please ensure your face is clearly visible, well-lit, and centered in the frame.'
                    }), 400

                # Ensure face image is properly sized
                face_img = cv2.resize(face_img, (200, 200))

                # Convert the face image to base64 for storage
                _, buffer = cv2.imencode('.jpg', face_img, [cv2.IMWRITE_JPEG_QUALITY, 90])
                face_data_base64 = base64.b64encode(buffer).decode('utf-8')

                # Generate a unique voter ID
                voter_id = generate_voter_id()

                # Create new voter
                new_voter = Voter(
                    voter_id=voter_id,
                    name=name,
                    age=age,
                    gender=gender,
                    phone=phone,
                    email=email,
                    address=address,
                    district=district,
                    state=state,
                    aadhar_number=aadhar_number,
                    photo_data=face_data_base64,
                    face_data=face_img
                )

                # Add voter to blockchain
                voter_data = {
                    "voter_id": voter_id,
                    "name": name,
                    "age": age,
                    "district": district,
                    "state": state,
                    "registration_time": time.time()
                }
                blockchain.add_voter_record(voter_data)
                blockchain.mine_pending_transactions()

                db.session.add(new_voter)
                db.session.commit()

                response_data = {
                    'status': 'success',
                    'message': f'Voter registered successfully! Your Voter ID is: {voter_id}',
                    'voter_id': voter_id
                }
                return jsonify(response_data)

            except Exception as e:
                print(f"Error processing photo: {str(e)}")
                return jsonify({
                    'status': 'error',
                    'message': 'Error processing photo. Please ensure the photo is clear, well-lit, and shows your face clearly.'
                }), 400

        except Exception as e:
            db.session.rollback()
            print(f"Error in voter registration: {str(e)}")
            return jsonify({
                'status': 'error',
                'message': f'Error registering voter: {str(e)}'
            }), 400

    return render_template('voter_registration.html')

@app.route('/voting', methods=['GET', 'POST'])
def voting():
    if request.method == 'POST':
        voter_id = request.form.get('voter_id')
        otp = request.form.get('otp')
        photo_data = request.form.get('photo_data')
        
        voter = Voter.query.filter_by(voter_id=voter_id).first()
        
        if not voter:
            flash('Invalid Voter ID', 'danger')
            return render_template('voting.html')
            
        if voter.has_voted:
            flash('You have already cast your vote', 'warning')
            return render_template('voting.html')
            
        if voter.is_disabled:
            flash('Your account has been disabled. Please contact the administrator.', 'danger')
            return render_template('voting.html')

        # First try face authentication
        if photo_data:
            try:
                # Convert base64 image to OpenCV format
                encoded_data = photo_data.split(',')[1]
                nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
                img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                # Detect face in the captured image
                face_img, face_loc = detect_face(img)
                
                if face_img is None:
                    flash('No face detected in the image. Please try again with better lighting and face alignment.', 'danger')
                    return render_template('voting.html', voter_id=voter_id, show_face=True)
                
                # Get stored face data
                stored_face_data = voter.face_data
                if stored_face_data is None:
                    flash('No face data found. Please contact the administrator.', 'danger')
                    return render_template('voting.html', voter_id=voter_id, show_face=True)
                
                # Compare faces
                match_score = compare_faces(face_img, stored_face_data)
                print(f"Face match score: {match_score}")
                
                # Lower threshold for better matching (adjust based on testing)
                threshold = 0.35
                
                if match_score >= threshold:
                    # Face verified successfully
                    session['voter_id'] = voter_id
                    return redirect(url_for('cast_vote'))
                else:
                    # Face verification failed, switch to OTP
                    flash('Face verification failed. Proceeding with OTP verification.', 'warning')
                    return render_template('voting.html', voter_id=voter_id, show_otp=True)
                    
            except Exception as e:
                print(f"Error in face verification: {str(e)}")
                flash('Error during face verification. Proceeding with OTP verification.', 'warning')
                return render_template('voting.html', voter_id=voter_id, show_otp=True)

        # If OTP is provided (after face auth failed)
        elif otp:
            # Verify OTP
            if otp != '2345':  # For testing purposes
                flash('Invalid OTP', 'danger')
                return render_template('voting.html', voter_id=voter_id, show_otp=True)
            
            # OTP verified successfully
            session['voter_id'] = voter_id
            return redirect(url_for('cast_vote'))

        # If no photo or OTP provided yet, show face capture interface
        return render_template('voting.html', voter_id=voter_id, show_face=True)

    return render_template('voting.html')

@app.route('/cast_vote', methods=['GET', 'POST'])
def cast_vote():
    if 'voter_id' not in session:
        return redirect(url_for('voting'))
        
    if request.method == 'POST':
        candidate_id = request.form.get('candidate')
        voter = Voter.query.filter_by(voter_id=session['voter_id']).first()
        candidate = Candidate.query.get(candidate_id)
        
        if voter and candidate and not voter.has_voted:
            # Create vote hash
            vote_data = {
                "voter_id": voter.voter_id,
                "candidate_id": candidate_id,
                "timestamp": time.time()
            }
            vote_hash = hashlib.sha256(json.dumps(vote_data).encode()).hexdigest()
            
            # Add vote to blockchain
            blockchain.add_vote_record(voter.voter_id, vote_hash)
            blockchain.mine_pending_transactions()
            
            # Update database
            candidate.votes += 1
            voter.has_voted = True
            db.session.commit()
            
            session.pop('voter_id', None)
            return render_template('vote_success.html')
            
    candidates = Candidate.query.all()
    return render_template('cast_vote.html', candidates=candidates)

@app.route('/election_management', methods=['GET', 'POST'])
def election_management():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
        
    if request.method == 'POST':
        name = request.form.get('name')
        party = request.form.get('party')
        photo = request.files.get('photo')
        
        if photo:
            try:
                # Generate a secure filename
                filename = f"{name.lower().replace(' ', '_')}_{int(time.time())}.jpg"
                # Store the photo path relative to static folder
                photo_path = f"images/{filename}"
                # Full path for saving the file
                full_path = os.path.join(app.static_folder, photo_path)
                
                # Ensure the directory exists
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                # Save the photo
                photo.save(full_path)
                
                # Verify the file was saved
                if os.path.exists(full_path):
                    new_candidate = Candidate(
                        name=name,
                        party=party,
                        photo_path=photo_path  # Store relative path
                    )
                    db.session.add(new_candidate)
                    db.session.commit()
                    flash('Candidate added successfully!')
                else:
                    flash('Error: Failed to save candidate photo.', 'error')
            except Exception as e:
                print(f"Error saving candidate photo: {str(e)}")
                flash('Error saving candidate photo. Please try again.', 'error')
        else:
            flash('Please select a photo for the candidate.', 'error')
            
    candidates = Candidate.query.all()
    return render_template('election_management.html', candidates=candidates)

def get_election_statistics():
    """Get detailed election statistics"""
    try:
        candidates = Candidate.query.all()
        total_votes = sum(c.votes for c in candidates)
        total_voters = Voter.query.count()
        voted_voters = Voter.query.filter_by(has_voted=True).count()
        
        # Voter turnout statistics
        turnout_percentage = (voted_voters / total_voters * 100) if total_voters > 0 else 0
        
        # District-wise voting statistics
        district_stats = db.session.query(
            Voter.district,
            db.func.count(Voter.id).label('total_voters'),
            db.func.sum(db.case([(Voter.has_voted, 1)], else_=0)).label('voted_count')
        ).group_by(Voter.district).all()
        
        district_data = {}
        for district, total, voted in district_stats:
            district_data[district] = {
                'total_voters': total,
                'voted_count': voted or 0,
                'turnout': ((voted or 0) / total * 100) if total > 0 else 0
            }
        
        # Age group voting statistics
        age_groups = {
            '18-25': (18, 25),
            '26-35': (26, 35),
            '36-50': (36, 50),
            '50+': (50, 200)
        }
        
        age_stats = {}
        for group, (min_age, max_age) in age_groups.items():
            if group == '50+':
                total = Voter.query.filter(Voter.age >= min_age).count()
                voted = Voter.query.filter(Voter.age >= min_age, Voter.has_voted == True).count()
            else:
                total = Voter.query.filter(Voter.age.between(min_age, max_age)).count()
                voted = Voter.query.filter(Voter.age.between(min_age, max_age), Voter.has_voted == True).count()
            
            age_stats[group] = {
                'total': total,
                'voted': voted,
                'percentage': (voted / total * 100) if total > 0 else 0
            }
        
        # Gender-wise voting statistics
        gender_stats = {}
        for gender in ['Male', 'Female', 'Other']:
            total = Voter.query.filter_by(gender=gender).count()
            voted = Voter.query.filter_by(gender=gender, has_voted=True).count()
            gender_stats[gender] = {
                'total': total,
                'voted': voted,
                'percentage': (voted / total * 100) if total > 0 else 0
            }
        
        # Time-based voting pattern
        voting_hours = db.session.query(
            db.func.strftime('%H', Voter.last_attempt).label('hour'),
            db.func.count(Voter.id).label('count')
        ).filter(Voter.has_voted == True).group_by('hour').all()
        
        hourly_voting = {str(h).zfill(2): 0 for h in range(24)}
        for hour, count in voting_hours:
            if hour:
                hourly_voting[hour] = count
        
        return {
            'total_votes': total_votes,
            'total_voters': total_voters,
            'voted_voters': voted_voters,
            'turnout_percentage': turnout_percentage,
            'district_stats': district_data,
            'age_stats': age_stats,
            'gender_stats': gender_stats,
            'hourly_voting': hourly_voting,
            'candidates': [{
                'name': c.name,
                'party': c.party,
                'votes': c.votes,
                'percentage': (c.votes / total_votes * 100) if total_votes > 0 else 0
            } for c in candidates]
        }
    except Exception as e:
        print(f"Error generating election statistics: {str(e)}")
        return None

@app.route('/results', methods=['GET', 'POST'])
def results():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
        
    if request.method == 'POST':
        # Check for fixed password instead of TOTP
        if request.form.get('2fa_code') == '12345':
            candidates = Candidate.query.order_by(Candidate.votes.desc()).all()
            total_votes = sum(c.votes for c in candidates)
            
            # Get detailed statistics
            statistics = get_election_statistics()
            
            # Pre-process statistics for charts
            chart_data = None
            if statistics:
                chart_data = {
                    'age_groups': {
                        'labels': list(statistics['age_stats'].keys()),
                        'voted_data': [stats['voted'] for stats in statistics['age_stats'].values()],
                        'total_data': [stats['total'] for stats in statistics['age_stats'].values()]
                    },
                    'gender_stats': {
                        'labels': list(statistics['gender_stats'].keys()),
                        'data': [stats['voted'] for stats in statistics['gender_stats'].values()]
                    },
                    'district_stats': {
                        'labels': list(statistics['district_stats'].keys()),
                        'data': [stats['turnout'] for stats in statistics['district_stats'].values()]
                    },
                    'hourly_voting': {
                        'labels': list(statistics['hourly_voting'].keys()),
                        'data': list(statistics['hourly_voting'].values())
                    }
                }
            
            return render_template(
                'results.html',
                candidates=candidates,
                total_votes=total_votes,
                show_results=True,
                statistics=statistics,
                chart_data=chart_data
            )
        flash('Invalid verification code. Please enter 12345.')
        
    return render_template('results.html', show_results=False)

@app.route('/voter/management')
def voter_management():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    voters = Voter.query.all()
    return render_template('voter_management.html', voters=voters)

@app.route('/voter/<voter_id>/details')
def voter_details(voter_id):
    if 'admin_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    
    voter = Voter.query.filter_by(voter_id=voter_id).first()
    if not voter:
        return jsonify({'error': 'Voter not found'}), 404
    
    # Convert face data to base64 if available
    photo_data = None
    if voter.face_data is not None:
        _, buffer = cv2.imencode('.jpg', voter.face_data)
        photo_data = base64.b64encode(buffer).decode('utf-8')
    
    return jsonify({
        'voter_id': voter.voter_id,
        'name': voter.name,
        'age': voter.age,
        'gender': voter.gender,
        'phone': voter.phone,
        'email': voter.email,
        'address': voter.address,
        'district': voter.district,
        'state': voter.state,
        'education': voter.education,
        'occupation': voter.occupation,
        'has_voted': voter.has_voted,
        'photo': photo_data
    })

@app.route('/voter/<voter_id>/delete', methods=['POST'])
def delete_voter(voter_id):
    if 'admin_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'}), 401
    
    voter = Voter.query.filter_by(voter_id=voter_id).first()
    if not voter:
        return jsonify({'success': False, 'error': 'Voter not found'}), 404
    
    try:
        db.session.delete(voter)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/voter/export')
def export_voters():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    
    import csv
    from io import StringIO
    
    voters = Voter.query.all()
    si = StringIO()
    writer = csv.writer(si)
    
    # Write header
    writer.writerow(['Voter ID', 'Name', 'Age', 'Phone', 'Address', 'Voting Status'])
    
    # Write data
    for voter in voters:
        writer.writerow([
            voter.voter_id,
            voter.name,
            voter.age,
            voter.phone,
            voter.address,
            'Voted' if voter.has_voted else 'Not Voted'
        ])
    
    output = si.getvalue()
    si.close()
    
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=voters.csv'}
    )

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_id', None)
    return redirect(url_for('admin_login'))

@app.route('/voter/analytics')
def voter_analytics():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    
    try:
        # Get statistics
        stats = get_voter_statistics()
        
        return render_template('voter_analytics.html', stats=stats)
                             
    except Exception as e:
        print(f"Error in voter analytics: {str(e)}")
        flash('An error occurred while loading analytics', 'error')
        return redirect(url_for('admin_dashboard'))

@app.route('/voter/<voter_id>/download_id_card')
def download_voter_id_card(voter_id):
    voter = Voter.query.filter_by(voter_id=voter_id).first()
    if not voter:
        flash('Voter not found', 'error')
        return redirect(url_for('admin_dashboard'))
    
    pdf_buffer = generate_voter_id_card(voter)
    
    response = make_response(pdf_buffer.getvalue())
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=voter_id_{voter_id}.pdf'
    
    return response

def init_db():
    """Initialize the database and create admin user if not exists"""
    try:
        with app.app_context():
            # Create all tables if they don't exist
            db.create_all()
            
            # Check if admin user exists
            admin = Admin.query.filter_by(username='admin').first()
            if not admin:
                # Create admin user with a known password
                admin = Admin(
                    username='admin',
                    password=generate_password_hash('admin123'),  # Changed password for testing
                    totp_secret=pyotp.random_base32()
                )
                db.session.add(admin)
                db.session.commit()
                print("Admin user created successfully!")
            else:
                print("Admin user already exists")
                
            # Verify tables exist
            inspector = inspect(db.engine)
            print("\nVerifying database tables:")
            print(f"Admin table exists: {inspector.has_table('admin')}")
            print(f"Voter table exists: {inspector.has_table('voter')}")
            print(f"Candidate table exists: {inspector.has_table('candidate')}")
                
    except Exception as e:
        print(f"Error initializing database: {str(e)}")
        raise

# Add function to check for duplicate voters
def check_duplicate_voter(aadhar_number, email, phone):
    """Check for duplicate voters based on Aadhar, email, and phone"""
    duplicate_checks = {
        'aadhar': Voter.query.filter_by(aadhar_number=aadhar_number).first(),
        'email': Voter.query.filter_by(email=email).first(),
        'phone': Voter.query.filter_by(phone=phone).first()
    }
    
    for field, value in duplicate_checks.items():
        if value:
            return True, f"A voter with this {field} already exists"
    return False, None

# Add analytics functions
def get_voter_statistics():
    """Get detailed voter statistics"""
    total_voters = Voter.query.count()
    total_voted = Voter.query.filter_by(has_voted=True).count()
    
    # Gender distribution
    male_voters = Voter.query.filter_by(gender='Male').count()
    female_voters = Voter.query.filter_by(gender='Female').count()
    other_voters = total_voters - male_voters - female_voters
    
    # Age distribution
    age_groups = {
        '18-25': Voter.query.filter(Voter.age.between(18, 25)).count(),
        '26-35': Voter.query.filter(Voter.age.between(26, 35)).count(),
        '36-50': Voter.query.filter(Voter.age.between(36, 50)).count(),
        '50+': Voter.query.filter(Voter.age > 50).count()
    }
    
    # District-wise distribution
    districts = db.session.query(Voter.district, 
                               db.func.count(Voter.id).label('count'))\
                         .group_by(Voter.district).all()
    
    # Education distribution
    education_dist = db.session.query(Voter.education, 
                                    db.func.count(Voter.id).label('count'))\
                              .group_by(Voter.education).all()
    
    # Voting time patterns (for voted users)
    voting_hours = db.session.query(
        db.func.extract('hour', Voter.last_attempt).label('hour'),
        db.func.count(Voter.id).label('count')
    ).filter(Voter.has_voted == True).group_by('hour').all()
    
    return {
        'total_voters': total_voters,
        'total_voted': total_voted,
        'voting_percentage': (total_voted / total_voters * 100) if total_voters > 0 else 0,
        'gender_distribution': {
            'male': male_voters,
            'female': female_voters,
            'other': other_voters
        },
        'age_distribution': age_groups,
        'district_distribution': dict(districts),
        'education_distribution': dict(education_dist),
        'voting_hours': dict(voting_hours)
    }

# Add new routes for blockchain functionality
@app.route('/blockchain/status')
def blockchain_status():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    
    chain_data = {
        "length": len(blockchain.chain),
        "is_valid": blockchain.is_chain_valid(),
        "pending_transactions": len(blockchain.pending_transactions),
        "latest_block": {
            "index": blockchain.get_latest_block().index,
            "hash": blockchain.get_latest_block().hash,
            "transactions": len(blockchain.get_latest_block().transactions)
        }
    }
    return render_template('blockchain_status.html', chain_data=chain_data)

@app.route('/blockchain/export')
def export_blockchain():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    
    response = make_response(blockchain.export_chain())
    response.headers['Content-Type'] = 'application/json'
    response.headers['Content-Disposition'] = 'attachment; filename=blockchain_export.json'
    return response

@app.route('/voter/<voter_id>/blockchain_history')
def voter_blockchain_history(voter_id):
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    
    voter = Voter.query.filter_by(voter_id=voter_id).first_or_404()
    history = blockchain.get_voter_history(voter_id)
    return render_template('voter_blockchain_history.html', voter=voter, history=history)

@app.route('/blockchain/verify')
def verify_blockchain():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))
    
    verification_data = {
        "chain_valid": blockchain.is_chain_valid(),
        "total_blocks": len(blockchain.chain),
        "blocks": []
    }
    
    # Get detailed information about each block
    for block in blockchain.chain:
        block_data = {
            "index": block.index,
            "timestamp": block.timestamp,
            "hash": block.hash,
            "previous_hash": block.previous_hash,
            "nonce": block.nonce,
            "transactions": {
                "total": len(block.transactions),
                "registrations": len([t for t in block.transactions if t["type"] == "voter_registration"]),
                "votes": len([t for t in block.transactions if t["type"] == "vote_cast"])
            }
        }
        verification_data["blocks"].append(block_data)
    
    return render_template('blockchain_verify.html', verification_data=verification_data)

# Add Jinja2 filter for timestamp formatting
@app.template_filter('format_timestamp')
def format_timestamp(timestamp):
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

@app.route('/check-duplicate', methods=['POST'])
def check_duplicate():
    field = request.form.get('field')
    value = request.form.get('value')
    
    if not field or not value:
        return jsonify({'error': 'Missing parameters'}), 400
    
    exists = False
    if field == 'aadhar':
        exists = Voter.query.filter_by(aadhar_number=value).first() is not None
    elif field == 'phone':
        exists = Voter.query.filter_by(phone=value).first() is not None
    elif field == 'email':
        exists = Voter.query.filter_by(email=value).first() is not None
    
    return jsonify({'exists': exists})

if __name__ == '__main__':
    # Initialize database before running the app
    init_db()
    
    print("\nServer is running on:")
    print("Local URL: http://127.0.0.1:5000")
    print("\nTo connect from your phone:")
    print("1. Make sure your phone is connected to the same WiFi network")
    print("2. Open your phone's browser and enter the Local URL")
    print("\nIf you still can't connect, check your Windows Firewall settings")
    
    # Run the app
    app.run(host='127.0.0.1', port=5000, debug=True) 