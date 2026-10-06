/* Synthetic transport fixture only; no trading behavior. */
extern unsigned long OpenSSL_version_num(void);
unsigned long synthetic_engine(void) { return OpenSSL_version_num(); }
