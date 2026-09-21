#                  REGISTER
#                     │
#                     ↓
#            email + password
#                     │
#                     ↓
#             hash_password()
#                     │
#                     ↓
#                 auth.db
#                     │
#                     │
#                     ↓
#                   LOGIN
#                     │
#                     ↓
#            email + password
#                     │
#                     ↓
#             verify_password()
#                     │
#                     ↓
#                  correct
#                     │
#                     ↓
#          create_access_token()
#                     │
#                     ↓
#              JWT + SECRET_KEY
#                     │
#                     ↓
#                   JWT
#                     │
#                     ↓
#             CLIENT KE PAAS
#                     │
#                     │
#                     ↓
#             GET /auth/me
#                     │
#                     │
#      Authorization: Bearer JWT
#                     │
#                     ↓
#          Depends(get_current_user)
#                     │
#                     ↓
#          Depends(security)
#                     │
#                     ↓
#              HTTPBearer
#                     │
#                     ↓
#          HTTPAuthorizationCredentials
#                     │
#                     ↓
#        credentials.credentials
#                     │
#                     ↓
#                    JWT
#                     │
#                     ↓
#               jwt.decode()
#                     │
#               SECRET_KEY
#               + HS256
#                     │
#                     ↓
#             JWT valid?
#                     │
#                     ↓
#              user_id = 1
#                     │
#                     ↓
#              auth.db lookup
#                     │
#                     ↓
#               Actual User
#                     │
#                     ↓
#               me(user)
#                     │
#                     ↓
#                  RESPONSE