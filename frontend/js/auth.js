import {initializeApp} from "https://www.gstatic.com/firebasejs/11.6.0/firebase-app.js";
import {
  getAuth,
  onAuthStateChanged,
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

let _currentUser = null;
let _idToken = null;
let _tokenExpiry = 0;

export function getCurrentUser() {
  return _currentUser;
}

export async function getIdToken() {
  if (!_currentUser) return null;
  // Refresh if within 5 minutes of expiry
  if (Date.now() > _tokenExpiry - 300000) {
    _idToken = await _currentUser.getIdToken(true);
    _tokenExpiry = Date.now() + 3600000;
  }
  return _idToken;
}

export async function authFetch(url, options = {}) {
  const token = await getIdToken();
  const headers = {...(options.headers || {})};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  return fetch(url, {...options, headers});
}

export async function signInWithGoogle() {
  await signInWithPopup(auth, googleProvider);
}

export async function signInWithEmail(email, password) {
  await signInWithEmailAndPassword(auth, email, password);
}

export async function signUpWithEmail(email, password, displayName) {
  const cred = await createUserWithEmailAndPassword(auth, email, password);
  if (displayName) await updateProfile(cred.user, {displayName});
}

export async function signOutUser() {
  _currentUser = null;
  _idToken = null;
  await signOut(auth);
}

export function waitForAuth() {
  return new Promise((resolve) => {
    const unsub = onAuthStateChanged(auth, async (user) => {
      unsub();
      _currentUser = user;
      if (user) {
        _idToken = await user.getIdToken();
        _tokenExpiry = Date.now() + 3600000;
      }
      resolve(user);
    });
  });
}

// Keep token fresh automatically
onAuthStateChanged(auth, async (user) => {
  _currentUser = user;
  if (user) {
    _idToken = await user.getIdToken();
    _tokenExpiry = Date.now() + 3600000;
  } else {
    _idToken = null;
  }
});
