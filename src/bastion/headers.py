"""HTTP header names shared by the API and its clients. Kept free of imports so that a client
(the console) does not load the server stack just to learn a header name."""

PASSCODE_HEADER = "X-Bastion-Passcode"
ACTOR_HEADER = "X-Bastion-Actor"
RUN_HEADER = "x-bastion-run"
