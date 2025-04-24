"use client";

import {
  createContext,
  useReducer,
  useEffect,
  ReactNode,
  Dispatch,
} from "react";

type User = {
  id: number;
  email: string;
  role: string;
  first_name: string;
  last_name: string;
  team: string;
  force_password_change: boolean;
};

type State = {
  user: User | null;
  isAuthReady: boolean;
};

type Action =
  | { type: "LOGIN"; payload: User }
  | { type: "LOGOUT" }
  | { type: "AUTH_READY" }
  | { type: "UPDATE_USER"; payload: User };

export const AuthContext = createContext<
  | { user: User | null; dispatch: Dispatch<Action>; isAuthReady: boolean }
  | undefined
>(undefined);
const authReducer = (state: State, action: Action): State => {
  switch (action.type) {
    case "LOGIN":
      return { ...state, user: action.payload };
    case "LOGOUT":
      return { ...state, user: null };
    case "AUTH_READY":
      return { ...state, isAuthReady: true };
    case "UPDATE_USER":
      return { ...state, user: action.payload };
    default:
      return state;
  }
};

export const AuthContextProvider = ({ children }: { children: ReactNode }) => {
  const [state, dispatch] = useReducer(authReducer, {
    user: null,
    isAuthReady: false,
  });

  useEffect(() => {
    const user = localStorage.getItem("user");
    if (user) {
      dispatch({ type: "LOGIN", payload: JSON.parse(user) });
    }
    dispatch({ type: "AUTH_READY" });
  }, []);

  return (
    <AuthContext.Provider
      value={{ user: state.user, dispatch, isAuthReady: state.isAuthReady }}
    >
      {children}
    </AuthContext.Provider>
  );
};
