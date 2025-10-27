"""
Authentication Processor Module
Handles pilot face recognition using InsightFace
"""
import json
import numpy as np
import logging
from typing import Dict, Any, Optional, Tuple


def normalize_embedding(embedding):
    """Normalize embedding to unit length consistently"""
    norm = np.linalg.norm(embedding)
    if norm > 1e-8:  # Avoid division by very small numbers
        return embedding / norm
    return embedding


def cosine_similarity(a, b):
    """Compute cosine similarity between normalized embeddings"""
    a_norm = normalize_embedding(a)
    b_norm = normalize_embedding(b)
    return np.dot(a_norm, b_norm)


class AuthenticatorProcessor:
    """
    Handle pilot face recognition for authentication.
    Processes frames to identify pilots against known embeddings.
    """

    def __init__(self, face_analyzer, logger: logging.Logger):
        self.face_analyzer = face_analyzer
        self.logger = logger
        self.pilot_embeddings = {}

        # Configuration
        self.recognition_threshold = 0.4
        self.detection_threshold = 0.5
        self.adaptive_detection_threshold = 0.5

        # Statistics tracking
        self.recognition_stats = {
            'total_frames': 0,
            'faces_detected': 0,
            'faces_recognized': 0,
            'avg_confidence': 0.0
        }

    def update_embeddings(self, embeddings: Dict[str, np.ndarray]):
        """Update pilot embeddings dictionary"""
        self.pilot_embeddings = embeddings
        self.logger.info(f"Updated {len(embeddings)} pilot embeddings")

    def process_frame(self, frame: np.ndarray) -> Dict[str, Any]:
        """
        Process a frame for face recognition.

        Returns:
            Dictionary containing:
            - pilot_username: Recognized pilot username or None
            - face_detected: Boolean indicating if face was detected
            - confidence: Recognition confidence score
            - detection_score: Face detection confidence
        """
        try:
            self.recognition_stats['total_frames'] += 1

            # Detect faces in frame
            faces = self.face_analyzer.get(frame)
            if not faces:
                return {
                    'pilot_username': None,
                    'face_detected': False,
                    'confidence': 0.0,
                    'detection_score': 0.0
                }

            # Use first/largest face
            face = faces[0]

            # Check face detection confidence
            detection_score = getattr(face, 'det_score', 1.0)

            if detection_score < self.adaptive_detection_threshold:
                self.logger.debug(f"Face detection confidence too low: {detection_score:.3f}")
                return {
                    'pilot_username': None,
                    'face_detected': False,
                    'confidence': 0.0,
                    'detection_score': detection_score
                }

            self.recognition_stats['faces_detected'] += 1

            # Get face embedding
            emb = normalize_embedding(face.embedding)

            # Compare against all known pilot embeddings
            best_match = None
            best_sim = -1.0

            for pilot_username, pilot_embedding in self.pilot_embeddings.items():
                sim = cosine_similarity(emb, pilot_embedding)
                if sim > best_sim:
                    best_sim = sim
                    best_match = pilot_username

            self.logger.debug(f"Best match: {best_match} with similarity: {best_sim:.3f}")

            # Check if confidence meets threshold
            if best_sim >= self.recognition_threshold:
                self.recognition_stats['faces_recognized'] += 1
                # Update running average confidence
                self.recognition_stats['avg_confidence'] = (
                    (self.recognition_stats['avg_confidence'] * (self.recognition_stats['faces_recognized'] - 1) + best_sim) /
                    self.recognition_stats['faces_recognized']
                )

                return {
                    'pilot_username': best_match,
                    'face_detected': True,
                    'confidence': float(best_sim),
                    'detection_score': float(detection_score)
                }

            # Face detected but not recognized
            return {
                'pilot_username': None,
                'face_detected': True,
                'confidence': float(best_sim),
                'detection_score': float(detection_score)
            }

        except Exception as e:
            self.logger.error(f"Authentication processing error: {e}")
            return {
                'pilot_username': None,
                'face_detected': False,
                'confidence': 0.0,
                'detection_score': 0.0
            }

    def update_adaptive_threshold(self):
        """Update detection threshold based on recent performance"""
        if self.recognition_stats['total_frames'] < 50:  # Need sufficient data
            return

        detection_rate = self.recognition_stats['faces_detected'] / self.recognition_stats['total_frames']
        recognition_rate = self.recognition_stats['faces_recognized'] / max(self.recognition_stats['faces_detected'], 1)

        # Adjust threshold based on performance
        if detection_rate < 0.1 and self.adaptive_detection_threshold > 0.3:
            self.adaptive_detection_threshold = max(
                self.adaptive_detection_threshold - 0.05,
                0.3
            )
            self.logger.info(f"Lowered detection threshold to {self.adaptive_detection_threshold:.2f}")
        elif detection_rate > 0.5 and recognition_rate < 0.1 and self.adaptive_detection_threshold < 0.5:
            self.adaptive_detection_threshold = min(
                self.adaptive_detection_threshold + 0.05,
                0.5
            )
            self.logger.info(f"Raised detection threshold to {self.adaptive_detection_threshold:.2f}")

    def reset_stats(self):
        """Reset recognition statistics"""
        self.recognition_stats = {
            'total_frames': 0,
            'faces_detected': 0,
            'faces_recognized': 0,
            'avg_confidence': 0.0
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get current recognition statistics"""
        return self.recognition_stats.copy()