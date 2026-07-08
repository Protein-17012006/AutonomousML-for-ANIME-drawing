# Iitial plan for expanding the current Copilot App layout

## 1. Context & Problem & Goal

The current Copilot Chat app is used anonymously and does not have role-based access per session, so any user can use the session by visiting `/copilot`

The goal is to implement authentication and chat history storage so that only signed in user can use the Copilot App to create and manage their own sessions and work. Anonymous users must sign in before getting into the Copilot space.

FOR URL IMPLEMENTATION, ASK ME IF YOU HAVE BETTER SUGGESTIONS AS HOW TO ORGANIZE ROUTES

## 2. Stages

To achieve this plan, there are three stages to follow (details of each stage is detailed after this section):

- First stage: Implement landing page (template + styles)
- Second stage: Implement login/signup pages (template + styles)
- Third stage: Implement backend services (authentication + chat history storage persistence)

## 3. Stage 1: Landing page

This page is served as the main entry point of our app, start at `/`
The page should contain following sections:

- Navigation bar: Brand Icon, Links (Home, About us, Highlight features) - these links when clicked will scroll users to its section in the page, A `Visit space` button, which when clicked will navigate the user to the Copilot space (if logged in) or to the log in page (if not logged in)
- Hero section: title, descriptions, two action buttons (`Create now` - similar to visit space on nav bar and `Explore now` - scrolls user to downstream sections)
- Milestones section: 4 cards, each card contains a logo (from Lucide icons), title, brief description (each card describes an imaginary achievement of our service)
- Background/About us section: title, description (background + mission), placeholder images of our team
- Highlight Features section: two columns, left is nav bar navigate each feature, right is feature overview (currently include three features of our app, frames to video, videos to frames, in-between fills)
- Newsletter section: title, description, a small email handling form for registering news from us, a placeholder image
- Footer: Brand Icon, brief quote, copyright claim, columns of links (based on our app)

## 4. Stage 2: Login/Signup pages

This page is used for authentication, allowing users to sign in with existing accounts, or sign up a new account

- Login page (`/login`): Inputs for email and password, option for sign up (direct user to signup page at /signup), third party log in options (Google, Github, Apple).
- Signup page (`/signup`): Inputs for email, password, password confirmation.
  For third-party logo usage, please verify me the sources of them
  AT THIS STAGE, ONLY IMPLEMENT THE TEMPLATES + STYLES, FUNCTIONALITY WILL BE HANDLED IN THE THIRD STAGE

## 5. Stage 3: Authentication + Chat history

The stage focuses entirely on backend implementation, particularly, authentication for login/signup pages created at `Stage 2` and persist chat message, chat history, resources uploaded from users and created from our ends so that sessions are live (details of this refer to `frontend\docs\plans\firebase-chat-persistence-plan.md`)
PLEASE DISCUSS WITH ME WHEN YOU COME TO THIS STAGE (REMEMBER TO READ THE `firebase-chat-persistence-plan.md` FIRST)
