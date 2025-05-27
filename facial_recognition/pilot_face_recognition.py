import os
import cv2
import numpy as np
import pickle
from insightface.app import FaceAnalysis

KNOWN_DIR = 'known_faces'
EMBEDDINGS_FILE = 'embeddings.pkl'

# Initialize the face analysis application
face_app = FaceAnalysis(name='buffalo_s', providers=['CPUExecutionProvider'])
face_app.prepare(ctx_id=0)

def load_known_embeddings():
    if os.path.exists(EMBEDDINGS_FILE):
        with open(EMBEDDINGS_FILE, 'rb') as f:
            return pickle.load(f)
    return {}

def save_embeddings(embeddings):
    with open(EMBEDDINGS_FILE, 'wb') as f:
        pickle.dump(embeddings, f)

def compute_embeddings_from_dir():
    embeddings = {}
    for person in os.listdir(KNOWN_DIR):
        person_dir = os.path.join(KNOWN_DIR, person)
        if not os.path.isdir(person_dir):
            continue
        person_embs = []
        for file in os.listdir(person_dir):
            path = os.path.join(person_dir, file)
            img = cv2.imread(path)
            if img is None:
                print(f"❌ Could not read image: {file}")
                continue
            faces = face_app.get(img)
            if not faces:
                print(f"❌ No face detected in {file}")
                continue
            emb = faces[0]['embedding']
            person_embs.append(emb)
            print(f"✅ Trained on {file} for {person}")
        if person_embs:
            # Average the embeddings per person
            avg_embedding = np.mean(person_embs, axis=0)
            embeddings[person] = avg_embedding
    return embeddings

def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def recognize(frame, known_embeddings, threshold=0.4):
    faces = face_app.get(frame)
    for face in faces:
        x1, y1, x2, y2 = list(map(int, face['bbox']))
        face_emb = face['embedding']
        print(face_emb.shape)

        best_match = "Unknown"
        best_sim = -1.0

        for person, known_emb in known_embeddings.items():
            sim = cosine_similarity(face_emb, known_emb)
            print(f"🔍 Similarity to {person}: {sim:.4f}")
            if sim > best_sim:
                best_sim = sim
                best_match = person

        name = best_match if best_sim > threshold else "Unknown"

        # Draw bounding box
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, name, (x1, y1 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)

    return frame

def main():
    if not os.path.exists(EMBEDDINGS_FILE):
        print("No trained embeddings found. Training...")
        known_embeddings = compute_embeddings_from_dir()
        save_embeddings(known_embeddings)
        print("Training complete.")
    else:
        known_embeddings = load_known_embeddings()

    print("Starting camera. Press 'q' to quit.")
    cap = cv2.VideoCapture(0)

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame = recognize(frame, known_embeddings)
        cv2.imshow("Face Recognition", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    main()
