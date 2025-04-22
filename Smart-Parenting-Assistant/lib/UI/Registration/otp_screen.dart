import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'dart:convert';
import 'package:http/http.dart' as http;
import '../dashboard.dart';
import 'login_screen.dart';
import 'dart:async';

class OtpScreen extends StatefulWidget {
  final String email;
  final bool isSignUp;
  const OtpScreen({
    super.key,
    required this.email,
    this.isSignUp = false,
  });

  @override
  State<OtpScreen> createState() => _OtpScreenState();
}

class _OtpScreenState extends State<OtpScreen> {
  final TextEditingController _otpController = TextEditingController();
  bool _isVerifying = false;
  bool _isButtonEnabled = false;
  bool _isResendAvailable = false;
  int _resendCountdown = 30;
  Timer? _resendTimer;

  @override
  void initState() {
    super.initState();
    _startResendTimer();
    _otpController.addListener(_checkOtpLength);
  }

  @override
  void dispose() {
    _otpController.dispose();
    _resendTimer?.cancel();
    super.dispose();
  }

  void _checkOtpLength() {
    setState(() {
      _isButtonEnabled = _otpController.text.trim().length == 6;
    });
  }

  void _startResendTimer() {
    setState(() {
      _isResendAvailable = false;
      _resendCountdown = 30;
    });

    _resendTimer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (_resendCountdown == 0) {
        timer.cancel();
        setState(() {
          _isResendAvailable = true;
        });
      } else {
        setState(() {
          _resendCountdown--;
        });
      }
    });
  }

  Future<void> resendOtp() async {
    final String url = "https://127.0.0.1:8000/resend-otp";

    await http.post(
      Uri.parse(url),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({"email": widget.email}),
    );

    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text("OTP has been resent")),
    );

    _startResendTimer();
  }

  Future<void> verifyOtp() async {
    setState(() => _isVerifying = true);

    final String url = widget.isSignUp
        ? "https://127.0.0.1:8000/signup-verify"
        : "https://127.0.0.1:8000/verify-otp";

    final response = await http.post(
      Uri.parse(url),
      headers: {"Content-Type": "application/json"},
      body: jsonEncode({
        "email": widget.email,
        "otp": _otpController.text.trim(),
      }),
    );

    setState(() => _isVerifying = false);

    if (response.statusCode == 200) {
      SharedPreferences prefs = await SharedPreferences.getInstance();
      await prefs.setBool("isLoggedIn", true);

      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("OTP verified successfully!")),
      );

      Future.delayed(const Duration(milliseconds: 500), () {
        if (widget.isSignUp) {
          Navigator.pushReplacement(
            context,
            MaterialPageRoute(builder: (context) => const LoginScreen()),
          );
        } else {
          Navigator.pushReplacement(
            context,
            MaterialPageRoute(builder: (context) => const Dashboard()),
          );
        }
      });
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text("Invalid OTP, please try again.")),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);

    return Scaffold(
      backgroundColor: const Color(0xFFF5F7FA),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(24.0),
          child: Card(
            elevation: 10,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(20),
            ),
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 36),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text(
                    "OTP Verification",
                    style: GoogleFonts.poppins(
                      fontSize: 24,
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                  const SizedBox(height: 10),
                  Text(
                    "Enter the 6-digit OTP sent to",
                    style: GoogleFonts.poppins(fontSize: 16),
                  ),
                  Text(
                    widget.email,
                    style: GoogleFonts.poppins(
                      fontSize: 16,
                      fontWeight: FontWeight.w600,
                      color: Colors.blueGrey[800],
                    ),
                  ),
                  const SizedBox(height: 30),
                  TextField(
                    controller: _otpController,
                    keyboardType: TextInputType.number,
                    maxLength: 6,
                    style: const TextStyle(letterSpacing: 4),
                    textAlign: TextAlign.center,
                    decoration: const InputDecoration(
                      counterText: "",
                      labelText: "Enter OTP",
                      border: OutlineInputBorder(),
                      contentPadding:
                          EdgeInsets.symmetric(vertical: 12, horizontal: 16),
                    ),
                  ),
                  const SizedBox(height: 25),
                  _isVerifying
                      ? const CircularProgressIndicator()
                      : SizedBox(
                          width: double.infinity,
                          child: ElevatedButton(
                            onPressed: _isButtonEnabled ? verifyOtp : null,
                            style: ElevatedButton.styleFrom(
                              padding: const EdgeInsets.symmetric(
                                  vertical: 14, horizontal: 24),
                              backgroundColor: _isButtonEnabled
                                  ? Colors.indigo
                                  : Colors.grey,
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(12),
                              ),
                            ),
                            child: const Text("Verify OTP"),
                          ),
                        ),
                  const SizedBox(height: 20),
                  _isResendAvailable
                      ? TextButton(
                          onPressed: resendOtp,
                          child: const Text("Resend OTP"),
                        )
                      : Text(
                          "Resend OTP in $_resendCountdown seconds",
                          style: TextStyle(
                            fontSize: 14,
                            color: Colors.grey[600],
                          ),
                        ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
