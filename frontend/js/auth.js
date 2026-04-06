import {initializeApp} from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js";
import {
  getAuth,
  signInWithPopup,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  GoogleAuthProvider,
  signOut,
  updateProfile,
} from "https://www.gstatic.com/firebasejs/11.6.0/firebase-auth.js";

const firebaseConfig = {
  apiKey: "AIzaSyCo7hX2iPhY0HcIzFmQXUyMe5O4AHS575I",
  authDomain: "app-01-488817.firebaseapp.com",
  projectId: "app-01-488817",
  storageBucket: "app-01-488817.firebasestorage.app",
  messagingSenderId: "348555315681",
  appId: "1:348555315681:web:8285cca752a1fffb5e2aa0",
};

const firebaseApp = initializeApp(firebaseConfig);
const auth = getAuth(firebaseApp);
const googleProvider = new GoogleAuthProvider();

// Always read directly from Firebase's own state — no manual caching that can go stale.

export function getCurrentUser() {
  return auth.currentUser;
}

export async function getIdToken() {
  const user = auth.currentUser;
  if (!user) return null;
  // Firebase caches the token internally and refreshes it automatically when needed.
  return user.getIdToken();
}

export async function signInWithGoogle() {
  // Popup-based sign-in: completes in the same page context so there is no
  // cross-page IndexedDB race condition that could lose the auth state.
  const result = await signInWithPopup(auth, googleProvider);
  return result.user;
}

export async function signInWithEmail(email, password) {
  await signInWithEmailAndPassword(auth, email, password);
}

export async function signUpWithEmail(email, password, displayName) {
  const cred = await createUserWithEmailAndPassword(auth, email, password);
  if (displayName) await updateProfile(cred.user, {displayName});
}

export async function signOutUser() {
  await signOut(auth);
}

export async function waitForAuth() {
  // authStateReady() resolves only after Firebase has finished reading persisted auth
  // state from IndexedDB, giving a reliable one-shot auth state check.
  await auth.authStateReady();
  return auth.currentUser;
}
