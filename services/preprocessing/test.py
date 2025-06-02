# test_blink_yawn.py

import cv2
import numpy as np
import mediapipe as mp
import time

# ---------------------------------------------------------------------
# Mediapipe Face Mesh initialization
# ---------------------------------------------------------------------
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=False,
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

# Landmark indices for EAR (Eye Aspect Ratio) and MAR (Mouth Aspect Ratio)
LEFT_EYE_LANDMARKS  = [33, 160, 158, 133, 153, 144]   # [outer, top-outer, top-inner, inner, bottom-inner, bottom-outer]
RIGHT_EYE_LANDMARKS = [263, 387, 385, 362, 380, 373]  # same pattern on right eye
MOUTH_LANDMARKS     = [13, 14, 78, 308, 61, 291]      # [upper_lip, lower_lip, left_corner, right_corner, top_inner, bottom_inner]

def compute_EAR(landmarks, indices, img_w, img_h):
    """
    Compute Eye Aspect Ratio (EAR):
      P1=outer corner, P2=top-outer, P3=top-inner, P4=inner corner, P5=bottom-inner, P6=bottom-outer
      EAR = (||P2-P6|| + ||P3-P5||) / (2 * ||P1-P4||)
    """
    pts = []
    for i in indices:
        lm = landmarks[i]
        x_px = int(lm.x * img_w)
        y_px = int(lm.y * img_h)
        pts.append((x_px, y_px))
    P1 = np.array(pts[0])
    P2 = np.array(pts[1])
    P3 = np.array(pts[2])
    P4 = np.array(pts[3])
    P5 = np.array(pts[4])
    P6 = np.array(pts[5])

    vert1 = np.linalg.norm(P2 - P6)
    vert2 = np.linalg.norm(P3 - P5)
    horiz = np.linalg.norm(P1 - P4)
    if horiz == 0:
        return 0.0
    ear = (vert1 + vert2) / (2.0 * horiz)
    return float(ear)

def compute_MAR(landmarks, indices, img_w, img_h):
    """
    Compute Mouth Aspect Ratio (MAR):
      P_upper = indices[0], P_lower = indices[1], P_left = indices[2], P_right = indices[3]
      MAR = ||P_upper - P_lower|| / ||P_left - P_right||
    """
    pts = []
    for i in indices:
        lm = landmarks[i]
        x_px = int(lm.x * img_w)
        y_px = int(lm.y * img_h)
        pts.append((x_px, y_px))
    P_upper = np.array(pts[0])
    P_lower = np.array(pts[1])
    P_left  = np.array(pts[2])
    P_right = np.array(pts[3])

    A = np.linalg.norm(P_upper - P_lower)
    B = np.linalg.norm(P_left - P_right)
    if B == 0:
        return 0.0
    mar = A / B
    return float(mar)

def main():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("Cannot open webcam.")
        return

    print("Press 'q' to quit.")
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            h, w = frame.shape[:2]
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = face_mesh.process(rgb)

            blink_score = 0.0
            yawn_score = 0.0

            if results.multi_face_landmarks:
                landmarks = results.multi_face_landmarks[0].landmark

                # Compute EAR for left and right eye
                ear_left = compute_EAR(landmarks, LEFT_EYE_LANDMARKS, w, h)
                ear_right = compute_EAR(landmarks, RIGHT_EYE_LANDMARKS, w, h)
                blink_score = (ear_left + ear_right) / 2.0

                # Compute MAR for mouth
                yawn_score = compute_MAR(landmarks, MOUTH_LANDMARKS, w, h)

                # Overlay EAR and MAR on frame
                cv2.putText(frame, f"Blink (EAR): {blink_score:.3f}", (10, 30),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                cv2.putText(frame, f"Yawn (MAR): {yawn_score:.3f}", (10, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

                # Optionally, draw landmarks for debugging
                #for idx in LEFT_EYE_LANDMARKS + RIGHT_EYE_LANDMARKS + MOUTH_LANDMARKS:
                #    lm = landmarks[idx]
                #    x_px = int(lm.x * w)
                #    y_px = int(lm.y * h)
                #    cv2.circle(frame, (x_px, y_px), 2, (0, 0, 255), -1)

            cv2.imshow("Blink/Yawn Test", frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        cv2.destroyAllWindows()
        face_mesh.close()

if __name__ == "__main__":
    main()
