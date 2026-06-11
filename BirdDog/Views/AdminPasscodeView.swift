import SwiftUI

struct AdminPasscodeView: View {

    @ObservedObject var appSettings: AppSettings
    @Environment(\.dismiss) private var dismiss

    @State private var enteredCode = ""
    @State private var shake = false
    @State private var wrongAttempt = false

    private let codeLength = 4

    var body: some View {
        NavigationStack {
            VStack(spacing: 32) {
                Spacer()

                Image(systemName: "lock.shield.fill")
                    .font(.system(size: 48))
                    .foregroundStyle(.blue)

                Text("Enter Admin Passcode")
                    .font(.title2.bold())

                codeDotsView
                    .offset(x: shake ? -10 : 0)
                    .animation(
                        shake ? .default.repeatCount(3, autoreverses: true).speed(6) : .default,
                        value: shake
                    )

                keypadView

                Spacer()
            }
            .padding()
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }

    private var codeDotsView: some View {
        HStack(spacing: 16) {
            ForEach(0..<codeLength, id: \.self) { index in
                Circle()
                    .fill(index < enteredCode.count ? (wrongAttempt ? Color.red : Color.blue) : Color.secondary.opacity(0.3))
                    .frame(width: 16, height: 16)
            }
        }
    }

    private var keypadView: some View {
        VStack(spacing: 12) {
            ForEach(keypadRows, id: \.self) { row in
                HStack(spacing: 16) {
                    ForEach(row, id: \.self) { key in
                        keyButton(key)
                    }
                }
            }
        }
    }

    private var keypadRows: [[String]] {
        [
            ["1", "2", "3"],
            ["4", "5", "6"],
            ["7", "8", "9"],
            ["", "0", "delete"],
        ]
    }

    @ViewBuilder
    private func keyButton(_ key: String) -> some View {
        if key.isEmpty {
            Color.clear
                .frame(width: 72, height: 72)
        } else if key == "delete" {
            Button {
                if !enteredCode.isEmpty {
                    enteredCode.removeLast()
                    wrongAttempt = false
                }
            } label: {
                Image(systemName: "delete.backward.fill")
                    .font(.title2)
                    .frame(width: 72, height: 72)
                    .foregroundStyle(.primary)
            }
        } else {
            Button {
                guard enteredCode.count < codeLength else { return }
                enteredCode.append(key)
                wrongAttempt = false

                if enteredCode.count == codeLength {
                    if appSettings.attemptUnlock(with: enteredCode) {
                        dismiss()
                    } else {
                        wrongAttempt = true
                        shake.toggle()
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                            enteredCode = ""
                        }
                    }
                }
            } label: {
                Text(key)
                    .font(.title.bold())
                    .frame(width: 72, height: 72)
                    .background(Color(.systemGray5), in: Circle())
                    .foregroundStyle(.primary)
            }
        }
    }
}
